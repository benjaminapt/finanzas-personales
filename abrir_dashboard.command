#!/bin/bash
cd "$(dirname "$0")"
open http://localhost:8501 &
python3 -m streamlit run dashboard/app.py --server.headless false
