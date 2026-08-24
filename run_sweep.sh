#!/bin/bash

STACK=$1  # e.g. naive_hf, tgi, vllm
export BENCHMARK_STACK=$STACK
HOST=${2:-http://localhost:8000}

if [ -z "$STACK" ]; then
  echo "Usage: ./run_sweep.sh <stack_name> [host]"
  exit 1
fi

CONCURRENCY_LEVELS=(1 5 10 20 30)
TRIALS=3
RUN_TIME="1m"

mkdir -p "results/$STACK"

for c in "${CONCURRENCY_LEVELS[@]}"; do
  for t in $(seq 1 $TRIALS); do
    echo "=== Stack: $STACK | Concurrency: $c | Trial: $t ==="
    locust -f shared/locustfile.py --host "$HOST" \
      --users "$c" --spawn-rate "$c" --run-time "$RUN_TIME" --headless \
      --csv "results/$STACK/c${c}_trial${t}"
    echo "=== Done. Sleeping 10s before next run ==="
    sleep 10
  done
done

echo "Sweep complete for $STACK."
