"""Separate RuBERT A (filter) or B (assessment + topics), safe local checkpoints."""
import json
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file
from transformers import AutoModel, BertConfig, BertModel


class PublicationModel(torch.nn.Module):
    def __init__(self, encoder, task):
        super().__init__()
        if task not in ('A', 'B'):
            raise ValueError('task must be A or B')
        self.encoder = encoder
        self.task = task
        self.dropout = torch.nn.Dropout(encoder.config.hidden_dropout_prob)
        hidden = encoder.config.hidden_size
        if task == 'A':
            self.inclusion = torch.nn.Linear(hidden, 2)
        else:
            self.assessment = torch.nn.Linear(hidden, 4)
            self.topics = torch.nn.Linear(hidden, 8)

    @classmethod
    def pretrained(cls, checkpoint, revision, task):
        return cls(AutoModel.from_pretrained(checkpoint, revision=revision, trust_remote_code=False), task)

    def forward(self, **inputs):
        encoded = self.encoder(**inputs)
        pooled = self.dropout(encoded.pooler_output)
        if self.task == 'A':
            return {'inclusion': self.inclusion(pooled)}
        return {'assessment': self.assessment(pooled), 'topics': self.topics(pooled)}

    def loss(self, logits, inclusion, assessment, topics):
        if self.task == 'A':
            return torch.nn.functional.cross_entropy(logits['inclusion'], inclusion)
        return (torch.nn.functional.cross_entropy(logits['assessment'], assessment)
                + torch.nn.functional.binary_cross_entropy_with_logits(logits['topics'], topics))

    def save(self, path, tokenizer, metadata):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=False)
        config = {'task': self.task, 'backbone_config': self.encoder.config.to_dict(), 'metadata': metadata}
        (path / 'publication_model.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        save_file({k: v.detach().cpu().contiguous() for k, v in self.state_dict().items()}, str(path / 'model.safetensors'))
        tokenizer.save_pretrained(path)

    @classmethod
    def load(cls, path):
        path = Path(path)
        config = json.loads((path / 'publication_model.json').read_text(encoding='utf-8'))
        model = cls(BertModel(BertConfig.from_dict(config['backbone_config'])), config['task'])
        model.load_state_dict(load_file(str(path / 'model.safetensors')), strict=True)
        return model
