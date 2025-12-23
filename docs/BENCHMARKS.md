# Performance Benchmarks

This document tracks the performance metrics of the Kryten LLM service, specifically the validation and generation subsystems.

## Methodology

Benchmarks are run using `pytest` with the `tests/test_validation_stress.py` suite.
- **Hardware:** Standard Dev Environment (Windows/Linux)
- **Python Version:** 3.12
- **Test Data:** 1000 iterations of standard text validation.

## Baseline Metrics (v1.0)

### Validation System

| Metric | Value | Description |
|--------|-------|-------------|
| **Throughput** | > 20,000 ops/sec | Validations per second (text only) |
| **Latency (Avg)** | < 0.05 ms | Average time per validation call |
| **Latency (Max)** | < 1.0 ms | Worst-case latency (99th percentile) |
| **Large Input** | < 10 ms | Validation of 50KB text block |
| **History Check** | < 1 ms | Repetition check against full history |

### LLM Generation (Estimated)

*Note: Dependent on external API or local hardware.*

| Provider | Latency (Avg) | Tokens/Sec | Notes |
|----------|---------------|------------|-------|
| **OpenAI (GPT-3.5)** | ~1.5s | ~50 | Network dependent |
| **OpenAI (GPT-4)** | ~3.0s | ~20 | Network dependent |
| **Ollama (Llama3)** | ~0.5s (TTFT) | ~30 | On NVIDIA RTX 3060 |

## Running Benchmarks

To run the validation stress tests and generate current metrics:

```bash
python -m pytest tests/test_validation_stress.py
```

## Optimization Tips

1. **Validation Latency:**
   - Disable `check_relevance` if not strictly required, as it involves more complex string matching.
   - Reduce `repetition_history_size` to limit comparison overhead.

2. **Memory Usage:**
   - The validation history is a fixed-size `deque`, so memory usage is constant and minimal (~few KB).
   - Large prompts/responses are transient.

3. **Throughput:**
   - The validation system is CPU-bound but extremely lightweight. It is unlikely to be a bottleneck compared to LLM network latency.
