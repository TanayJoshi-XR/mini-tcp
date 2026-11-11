#!/bin/bash
set -e
export MPLBACKEND=Agg
python -m tests.test_congestion
python -m tests.mini_tcp_demo
python -m tests.cc_demo
python -m experiments.cwnd_plot
python -m experiments.fairness
python -m experiments.cc_compare
echo "ALL DONE - charts are in results/"
