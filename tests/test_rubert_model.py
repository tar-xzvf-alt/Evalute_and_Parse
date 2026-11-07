"""Run on the isolated training environment; skip without optional ML packages."""
import importlib.util
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ML_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ('torch', 'transformers', 'safetensors'))


@unittest.skipUnless(ML_AVAILABLE, 'optional training dependencies not installed')
class PublicationModelTests(unittest.TestCase):
    def test_both_tasks_loss_backward_and_safe_roundtrip(self):
        import torch
        from transformers import BertConfig, BertModel, BertTokenizerFast
        from src.rubert_model import PublicationModel

        torch.manual_seed(7)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            vocab = folder / 'vocab.txt'
            vocab.write_text('[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nтекст\nрегион\n', encoding='utf-8')
            tokenizer = BertTokenizerFast(vocab_file=str(vocab))
            for task in ('A', 'B'):
                with self.subTest(task=task):
                    config = BertConfig(vocab_size=7, hidden_size=16, num_hidden_layers=1,
                                        num_attention_heads=2, intermediate_size=32,
                                        hidden_dropout_prob=0., attention_probs_dropout_prob=0.)
                    model = PublicationModel(BertModel(config), task)
                    inputs = tokenizer(['регион', 'регион'], ['текст', 'текст'], return_tensors='pt')
                    logits = model(**inputs)
                    loss = model.loss(logits, torch.tensor([0, 1]), torch.tensor([0, 3]), torch.zeros(2, 8))
                    loss.backward()
                    self.assertTrue(torch.isfinite(loss))
                    for head in ([model.inclusion] if task == 'A' else [model.assessment, model.topics]):
                        self.assertIsNotNone(head.weight.grad)
                        self.assertTrue(torch.isfinite(head.weight.grad).all())
                    target = folder / task
                    model.save(target, tokenizer, {'seed': 7})
                    restored = PublicationModel.load(target)
                    self.assertEqual(restored.task, task)
                    for key, value in restored(**inputs).items():
                        torch.testing.assert_close(value, logits[key])
                    with self.assertRaises(FileExistsError):
                        model.save(target, tokenizer, {})

    def test_unknown_task_rejected(self):
        from transformers import BertConfig, BertModel
        from src.rubert_model import PublicationModel
        with self.assertRaises(ValueError):
            PublicationModel(BertModel(BertConfig(hidden_size=16, num_hidden_layers=1,
                                                 num_attention_heads=2, intermediate_size=32)), 'C')

    def test_tiny_gpu_training_loop_without_network_or_real_data(self):
        import json
        import torch
        from transformers import BertConfig, BertModel, BertTokenizerFast
        from src.rubert_model import PublicationModel
        from src.rubert_training import run

        if not torch.cuda.is_available():
            self.skipTest('CUDA required for the actual training-loop smoke test')
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder); dataset = folder / 'dataset'; dataset.mkdir()
            vocab = folder / 'vocab.txt'
            vocab.write_text('[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nтекст\nрегион\n', encoding='utf-8')
            tokenizer = BertTokenizerFast(vocab_file=str(vocab))
            (dataset / 'manifest.json').write_text(json.dumps({'artifact_sha256': {}, 'checkpoint': 'test-local',
                                                              'revision': 'test', 'status': 'synthetic_smoke_only'}))
            for split, count in [('train', 4), ('validation', 2), ('test', 2)]:
                rows = [{'id': split + str(i), 'split': split, 'near_group_id': split + str(i),
                         'include': True, 'assessment': ['positive', 'negative', 'mixed', 'unassessable'][i],
                         'topics': [5], 'source_region': 'регион', 'text': 'текст текст'} for i in range(count)]
                (dataset / (split + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
            for task in ('A', 'B'):
                def make_model(*unused):
                    config = BertConfig(vocab_size=7, hidden_size=16, num_hidden_layers=1,
                                        num_attention_heads=2, intermediate_size=32)
                    return PublicationModel(BertModel(config), task)
                target = folder / task
                args = Namespace(command='train', dataset=str(dataset), output=str(target), task=task,
                                 max_length=128, batch_size=2, accumulation=2, epochs=1, updates=1,
                                 learning_rate=2e-5, seed=7)
                with patch('transformers.AutoTokenizer.from_pretrained', return_value=tokenizer), \
                     patch.object(PublicationModel, 'pretrained', side_effect=make_model):
                    run(args)
                completed = json.loads((target / 'completed.json').read_text())
                self.assertEqual(completed['optimizer_updates'], 1)
                self.assertFalse(completed['test_metrics_computed'])
                self.assertEqual(PublicationModel.load(target / 'checkpoint_epoch_1').task, task)
                torch.cuda.empty_cache()


if __name__ == '__main__':
    unittest.main()
