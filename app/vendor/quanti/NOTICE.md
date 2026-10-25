# Quanti code included in this distribution

Upstream: https://github.com/coo-moon/quanti
Retrieved: 2026-10-25, via GitHub codeload main archive.
License: MIT, Copyright (c) 2026 Quanti Contributors; full text in LICENSE alongside this file.

Files: screeners/ma_trend.py and screeners/rsi_oversold.py.
Only modifications: two imports changed to `.support` to avoid loading the upstream execution/model runtime. Algorithm bodies are unchanged. support.py is our minimal local adapter, not upstream's complete domain model.

SHA-256 of original archive files, before import edits:

- ma_trend.py: 0f4443293d7bc2c116cc4195eee05035f83a5f287dfdab8e9b386745313ef5c5
- rsi_oversold.py: 4045372a8c810d7c1f382277be82e09864378d9e8b7bbab6379170e841d96eed

Upstream commit SHA could not be resolved due unauthenticated API rate limit and Git transport failure. Content hashes identify the reviewed source snapshot. The vendored files remain local and do not auto-update. A future update requires source comparison and regression tests.

Review: both screeners only perform arithmetic on supplied closing prices (plus NumPy for RSI); no network, file writes, dynamic evaluation, plugin loading, broker or order API. Defaults are fixed locally. Input prices are checked for positive finite values before scoring. Minimum histories are 60/15 respectively. Tests cover trend/non-trend, falling and flat prices, warm-up and historical truncation. Quanti RSI uses simple mean gains/losses, unlike ta's Wilder RSI. Upstream returns zero for zero average loss, including flat prices; preserved deliberately. None of this constitutes profitability validation or a security audit of the whole upstream project.
