"""CUDA/Transformers technical smoke-test. No downloads or publication data."""
import json
import platform


def main():
    import torch
    import transformers
    from transformers import BertConfig, BertModel

    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; refusing to silently test on CPU')
    torch.manual_seed(20261107)
    device = torch.device('cuda:0')
    config = BertConfig(
        vocab_size=256, hidden_size=64, num_hidden_layers=2,
        num_attention_heads=4, intermediate_size=128, max_position_embeddings=64,
    )
    encoder = BertModel(config).to(device)
    filter_head = torch.nn.Linear(64, 2).to(device)
    assessment_head = torch.nn.Linear(64, 4).to(device)
    topic_head = torch.nn.Linear(64, 8).to(device)
    inputs = torch.randint(0, 256, (2, 32), device=device)
    pooled = encoder(input_ids=inputs, attention_mask=torch.ones_like(inputs)).pooler_output
    inclusion, assessment, topics = filter_head(pooled), assessment_head(pooled), topic_head(pooled)
    loss = (
        torch.nn.functional.cross_entropy(inclusion, torch.tensor([0, 1], device=device))
        + torch.nn.functional.cross_entropy(assessment, torch.tensor([0, 3], device=device))
        + torch.nn.functional.binary_cross_entropy_with_logits(topics, torch.zeros_like(topics))
    )
    if not torch.isfinite(loss):
        raise RuntimeError('Nonfinite loss')
    loss.backward()
    torch.cuda.synchronize()
    if any(p.grad is None or not torch.isfinite(p.grad).all() for head in (filter_head, assessment_head, topic_head) for p in head.parameters()):
        raise RuntimeError('Missing or nonfinite head gradients')
    print(json.dumps({
        'status': 'passed', 'python': platform.python_version(),
        'torch': torch.__version__, 'transformers': transformers.__version__,
        'cuda_runtime': torch.version.cuda, 'gpu': torch.cuda.get_device_name(0),
        'compute_capability': list(torch.cuda.get_device_capability(0)),
        'compiled_architectures': torch.cuda.get_arch_list(),
        'vram_total_mib': torch.cuda.get_device_properties(0).total_memory // 2**20,
        'peak_allocated_mib': round(torch.cuda.max_memory_allocated() / 2**20, 2),
        'logit_shapes': [list(t.shape) for t in (inclusion, assessment, topics)],
        'finite_backward': True, 'pretrained_weights_downloaded': False,
        'publication_data_used': False, 'optimizer_steps': 0,
        'scope': 'tiny random BERT; not full-size RuBERT memory/performance validation',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
