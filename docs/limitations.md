# Known limitations

## Warmup inconsistency across stacks
- Naive HF and TGI sweeps did not use the formal automated warmup step (added to `run_sweep.sh` later, after vLLM's cold-start issue surfaced during testing).
- Their `c1_trial1` results may carry a small residual cold-start effect, though incidental manual curl testing performed before each sweep likely provided partial warmup.
- vLLM's sweep uses the formal 8-request warmup baked into `run_sweep.sh`.
- Decision: documented here as a known limitation rather than rerunning naive HF/TGI, to preserve project momentum. A more rigorous version of this project would rerun all three stacks' `c1_trial1` under identical formal warmup conditions.
