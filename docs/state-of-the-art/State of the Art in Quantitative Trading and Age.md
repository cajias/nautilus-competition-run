# State of the Art in Quantitative Trading and Agentic Strategy Generation: A Practitioner's Report for NautilusTrader + Binance

## TL;DR

- **TimesFM is useful for crypto only as one signal among many, and only with caveats.** TimesFM-2.5 (200M params, 16,384-token context, GIFT-Eval #1 zero-shot at release) is genuinely state-of-the-art on general benchmarks, but the most rigorous 2025–2026 financial studies (Rahimikia, Ni & Wang 2025; Kronos paper, AAAI 2026; Marconi 2025) consistently find that **off-the-shelf TSFMs underperform on raw return forecasting and only become competitive after domain-specific pre-training or careful fine-tuning**. For Binance perpetual K-lines you should treat TimesFM as a generic signal generator, fine-tune it (LoRA on 1m–1h crypto bars), or — better still — use Kronos, the only open foundation model pre-trained specifically on 12B K-lines from 45 exchanges.
- **Agentic alpha generation works, but the empirical evidence is narrow and look-ahead-biased.** The strongest peer-reviewed result is Microsoft's RD-Agent(Q) (NeurIPS 2025), which delivers ~2× the annualized return of classical factor libraries with 70% fewer factors at <$10/run on Chinese A-shares. Multi-agent trading systems (TradingAgents, FinAgent, FinCon, QuantAgents) report Sharpe 2–3 and 30–90% returns, but 2025 work (*Profit Mirage*, *Look-Ahead-Bench*, Glasserman & Lin) shows these results are largely artifacts of LLM training-data leakage that **collapse ~50% out-of-cutoff**. The honest baseline is: agent pipelines are real productivity tools for *factor/code generation*, but their reported PnL should be discounted heavily.
- **For a NautilusTrader+Binance build, the highest-value architecture is a hybrid: classical microstructure baselines + a fine-tuned crypto TSFM (Kronos or TimesFM-LoRA) wired as a tool an RD-Agent-style multi-agent loop can call, with strict purged/embargoed walk-forward, deflated Sharpe, and post-cutoff out-of-sample gates.** Avoid letting LLM agents make trade decisions directly; use them to generate, code, and stress-test alpha expressions that are then validated by the same Lopez-de-Prado pipeline you would apply to a human-written strategy.

---

## PART 1 — STATE OF THE ART OF QUANTITATIVE TECHNIQUES (2024–2026)

### 1. Time-Series Foundation Models — The Main Focus

#### 1.1 Google TimesFM (1.0 → 2.0 → 2.5 → ICF)

**Architecture and lineage.** TimesFM, introduced in Das et al., *"A decoder-only foundation model for time-series forecasting"* (ICML 2024, arXiv 2310.10688), is a decoder-only transformer that patches the input series, embeds patches via a shared residual MLP, and autoregressively predicts the next patch. Pretraining mixes ~100B real-world time points (Wikipedia Pageviews, Google Trends, M4, electricity, traffic) with ~50% synthetic ARMA series.

| Version | Params | Max context | Probabilistic head | Notes |
|---|---|---|---|---|
| TimesFM-1.0 | 200M | 512 | Experimental quantile | Initial Apache-2.0 release (mid-2024) |
| TimesFM-2.0 | 500M | 2,048 | Experimental quantile | Adds LOTSA pretraining (Salesforce) |
| TimesFM-2.5 | **200M** | **16,384** | 30M continuous quantile head, up to 1,000-step horizons | Released Sep 2025; QKV fusion, RoPE, QK-norm; Mar 2026 update restored XReg covariate support |

**Benchmarks.** On **GIFT-Eval** (Salesforce, NeurIPS 2024 — 28 datasets, multi-frequency, multi-horizon), TimesFM-2.5 ranked #1 among zero-shot foundation models on both MASE (point) and CRPS (probabilistic) at release. It was the first FM to beat AutoTheta on second-level frequency. Amazon's Chronos-2 (Oct 2025) subsequently surpassed it on covariate-informed tasks.

**TimesFM-ICF (In-Context Fine-Tuning).** Das et al., *"In-Context Fine-Tuning for Time-Series Foundation Models"* (arXiv 2410.24087, ICML 2025) introduces a continued-pretraining phase where related in-context series are concatenated through a learned separator token. ICF improves base TimesFM by **+6.8%** scaled-MASE on the Chronos OOD benchmark and matches dataset-specific full fine-tuning *without weight updates at inference*. The full OOD benchmark runs 16× faster than standard FT (25 min vs 418 min). A related CIKM 2025 paper (Xu et al., *"In-context Pre-trained Time-Series Foundation Models adapt to Unseen Tasks"*) reports ~11.4% gains on unseen tasks.

**Practical limits and integration.** Inference API: `TimesFM_2p5_200M_torch.from_pretrained(...)` supports `max_context=1024–16384`, `max_horizon` up to 256 (1,000 with continuous quantile head), 10 quantiles (10–90th percentile). Available via Hugging Face, BigQuery ML `AI.FORECAST`, Google Sheets, Vertex Model Garden. Covariate (XReg) support was restored in Oct 2025 / Mar 2026 updates.

#### 1.2 Competing Foundation Models

| Model | Org | Release | Architecture | Context | Distinctive feature |
|---|---|---|---|---|---|
| **Chronos / Chronos-Bolt / Chronos-2** | Amazon Science | 2024–Oct 2025 | T5 encoder-decoder; tokenized values | 512–2048 | Chronos-Bolt is 250× faster, 20× memory-efficient; **Chronos-2** has zero-shot multivariate + covariate support and ≥90% head-to-head win-rate vs Bolt; #1 on fev-bench/GIFT-Eval at release |
| **Moirai → Moirai-MoE** | Salesforce | 2024–Nov 2024 | Encoder, sparse MoE | 5,000+ | First MoE TSFM; +17% over dense Moirai on Monash; outperforms TimesFM/Chronos with 65× fewer activated params; LOTSA pretraining |
| **Lag-Llama** | ServiceNow / Mila / Morgan Stanley | 2023 | Decoder, lagged covariates | 32 (default) | Probabilistic Student-t output; explicitly recommends fine-tuning |
| **TimeGPT-1 / TimeGPT-2** | Nixtla | 2023–2024 | Closed-source transformer | – | API-only; CoinDesk fine-tuned variant on ~2.8GB minute crypto data (BTC/ETH/ADA/XRP/SOL) |
| **Tiny Time Mixers (TTM-A/B/E)** | IBM Granite | NeurIPS 2024 | MLP-Mixer (non-transformer) | 512–1536 | <1M params; outperforms Chronos by 17–32%, Lag-Llama by 40%, TimesFM-2.0 by 19% on standard benches; CPU-friendly |
| **MOMENT** | CMU | ICML 2024 | T5 encoder, masked patch reconstruction | 512 | Multi-task (forecast/classification/anomaly/imputation) |
| **Toto + BOOM** | Datadog | 2024–2025 | Decoder, factorized space-time attention, Student-t mixture | 4,096 | Trained on 2.36T tokens (~70% Datadog telemetry); SOTA on observability and GIFT-Eval; NOT designed for finance |
| **Kronos** | Tsinghua (Shi et al., AAAI 2026) | Aug 2025 | Decoder w/ specialized OHLCVA tokenizer | 512 | **Crypto-relevant**: pretrained on 12B K-lines from 45 exchanges; +93% RankIC over best TSFM on price forecasting, +9% MAE on volatility, +22% generative fidelity |

#### 1.3 Empirical Evidence on Financial / Crypto Data

This is the most important section for the user. The most rigorous studies converge on a sobering conclusion: **off-the-shelf zero-shot TSFMs do not deliver alpha on financial returns; only domain-specific pretraining or careful fine-tuning works.**

- **Rahimikia, Ni & Wang, "Re(Visiting) Time Series Foundation Models in Finance"** (arXiv 2511.18578, Nov 2025) — first comprehensive empirical study across global markets, 18M+ daily excess returns over 2001–2023. **Off-the-shelf TSFMs perform poorly in zero-shot AND fine-tuning settings.** Models pre-trained from scratch on financial data achieve "substantial" gains. Ensemble GBMs (CatBoost/XGBoost/LightGBM) consistently outperform linear baselines and most neural networks across 5/21/252/512-day rolling windows.
- **Kronos paper (Shi et al., AAAI 2026, arXiv 2508.02739)** — Kronos beats TimesFM, Moirai, Chronos, MOMENT, TimeMOE in zero-shot on K-line data; explicitly attributes generic TSFMs' weakness to mis-aligned inductive biases (financial data has low SNR, non-stationarity, OHLCVA dependencies that are sparse in pretraining corpora).
- **Marconi, "Time Series Foundation Models for Multivariate Financial Time Series Forecasting"** (arXiv 2507.07296, Jul 2025) — Pretrained TTM fine-tuned on FX/rates achieves 25–50% better performance than identical-architecture untrained models on limited data, 15–30% on lengthier datasets. Confirms that *fine-tuning is the key value-add*, not zero-shot.
- **Pfn / pfnet-research timesfm_fin paper** (Yi et al., arXiv 2412.09880) — Continual pretraining of TimesFM on ~100M finance time points (S&P500, TOPIX500, FX, **crypto**); the fine-tuned model outperforms benchmarks on returns, Sharpe, max drawdown, transaction cost. Code at `github.com/pfnet-research/timesfm_fin`. This is the most directly relevant published result for the user.
- **CTBench (Ang et al., NeurIPS 2025, arXiv 2508.02758)** — First cryptocurrency-specific time-series-generation benchmark; 452 Binance USDT pairs, 2020–2024 hourly. Found pronounced trade-offs between statistical fidelity and tradability; diffusion-based models give lowest forecast error but highest turnover and worst net-of-fee Sharpe; KoVAE collapses under fees.
- **CoinDesk × Nixtla** experiment (Medium, 2024) — fine-tuned TimeGPT on minute BTC/ETH/ADA/XRP/SOL produced reasonable point forecasts but the article does not provide deflated-Sharpe or live PnL.

#### 1.4 Practical Limitations

1. **Probabilistic calibration is weak.** TimesFM 1.0/2.0 quantile heads were marked experimental; calibration drifts on heavy-tailed crypto returns. Toto's Student-t mixture and Kronos's discrete tokenization are better suited.
2. **Look-ahead via pretraining-corpus overlap.** TimesFM training cutoffs (Wikipedia Nov 2023, Google Trends EoY 2022) and Chronos training data may overlap your backtest. Any backtest before mid-2024 should be considered contaminated unless you verify dataset-level exclusion. This is the **time-series analog of the LLM "Profit Mirage" problem**.
3. **Regime shifts and non-stationarity.** Even Kronos-quality models show RankIC degradation across regime breaks; the recently popular "BERT² moment" workshop (NeurIPS 2025) explicitly questioned whether scaling alone can fix this.
4. **Autoregressive error accumulation** at long horizons (decoder-only TimesFM, Kronos) — accuracy drops sharply beyond ~horizon 100 patches.
5. **Univariate bias.** Original TimesFM is univariate; covariate support (XReg, Mar 2026) is regression-on-residuals, not joint multivariate. Chronos-2 and Moirai-MoE handle covariates natively.
6. **Crowding risk.** Once Kronos/TimesFM-style models become widely deployed, the patterns they learn get arbitraged away (Kinlay 2026).

### 2. Classical Quantitative Techniques Still in Heavy Use

These remain the *production baselines that any TSFM-driven strategy must beat after costs*.

- **Factor models in crypto.** Standard equity factors (size, value, momentum, low-vol) have crypto analogues: cross-sectional momentum (1–4 week lookback) is the most robust; "value" via MVRV / NVT (LookIntoBitcoin); "carry" via funding rate sign; "size" via market-cap deciles excluding stablecoins. The Liu-Tsyvinski-Wu factor model for crypto (JoF 2022) is the standard reference; Liu-Tsyvinski (RFS 2021) documented size/momentum risk premia.
- **Statistical arbitrage / cointegration / pairs.** Engle-Granger and Johansen tests on log-prices, half-life filters, OU residual modeling. In crypto, the most reliable application is **cross-exchange pairs** (BTC-USDT Binance vs. BTC-USDT Coinbase/Kraken), exploited under a Cartea-style impulse-control framework. CTBench's "Statistical Arbitrage" task uses precisely this OU residual setup.
- **Mean reversion (Ornstein-Uhlenbeck) and trend-following.** Time-series momentum (Moskowitz 2012) generalizes to crypto with Sharpe ~0.7 net of costs across 2017–2023 universe; OU-based reversion is dominant on stablecoin pairs, ETH/BTC, and intraday on majors.
- **Volatility forecasting.** GARCH(1,1) and HAR-RV (Corsi 2009) remain the strongest *interpretable* baselines; HAR-RV with realized kernels routinely beats neural nets at 1-day horizons on BTC/ETH (Bollerslev surveys). For implied vol, Deribit term-structure surfaces are the de-facto data; SVI parameterization is standard. Kronos delivers 9% lower MAE than GARCH on volatility forecasting in its paper.
- **Market microstructure.** Cont-Kukanov-Stoikov OFI (Cont et al. 2014) and its multi-level "Deep OFI" extension (Kolm et al., *Mathematical Finance* 2023) are highly predictive at short horizons. Kyle (1985) lambda and Glosten-Milgrom (1985) PIN-style models give an information-asymmetry framework. For execution: **Almgren-Chriss** (closed form), **Cartea-Jaimungal-Penalva** *Algorithmic and High-Frequency Trading* (CUP 2015) for limit-order/market-order mixed control, Guéant for market making.
- **Portfolio construction.** Mean-variance and Black-Litterman remain standard but unstable on crypto's ill-conditioned covariance matrix. **Hierarchical Risk Parity (Lopez de Prado 2016, JPM)** is the recommended robust default — it uses single-linkage clustering, quasi-diagonalization, and recursive bisection, doesn't require matrix inversion, and empirically delivers lower OOS variance than minimum-variance/CLA. Risk parity at the cluster level (ERC) is competitive.

### 3. Modern ML/DL Beyond Foundation Models

- **Transformer/MLP forecasters.** **PatchTST** (Nie et al., ICLR 2023) achieved 21% MSE / 17% MAE reduction over prior transformers; remains a strong supervised baseline. **iTransformer** (ICLR 2024) inverts attention to the variate dimension. **N-BEATS** (Oreshkin, ICLR 2020) and **N-HiTS** (Challu, AAAI 2023) are MLP-based and dominate the 918-experiment benchmark by Saidd (arXiv 2603.16886, 2026) on crypto/forex/equity at 4h and 24h horizons — **ModernTCN** ranks #1, PatchTST #2, while directional accuracy stays at 50% for all MSE-trained models, an important reality check. **TFT** (Lim 2021) underperforms in finance per Emerald 2024 study. **Autoformer/Informer** are workable but generally beaten by PatchTST.
- **Graph neural networks.** GCN-LSTM hybrids (Tandfonline 2022) outperform multivariate LSTMs on crypto co-movement; EMGNN (Springer Financial Innovation 2025) models cryptocurrency-conventional market spillover. T3GNN handles Web3 social transaction prediction. Practical caveat: graph topology specification is fragile and scaling to a 200-coin universe is nontrivial.
- **Reinforcement learning.** **FinRL / FinRL-Meta / FinRL Contests 2023–2025** (Liu et al., NeurIPS 2022 + arXiv 2504.02281, *AI for Engineering* 2025) provide gym-style env for crypto trading; Sharpe ~0.28 on BTC ensemble agents (modest). **TradeMaster** and **AlphaMix+** push RL further (DeepTrader Sharpe 1.27). PPO/SAC are workhorses; massive-parallel GPU envs achieve 1,650× sampling speedup.
- **Regime detection.** HMMs (Hamilton, Baum-Welch), Bayesian online change-point (Adams-MacKay 2007), and kernel CUSUM. Useful as *gating* signals for switching strategies; rarely standalone alpha.
- **Self-supervised representation learning.** **TS2Vec** (AAAI 2022), **TF-C** (NeurIPS 2022), **SimMTM** (NeurIPS 2023). New TS2Vec-Ensemble (arXiv 2511.22395, 2025) fuses TS2Vec embeddings with explicit seasonal priors and beats baselines on ETT. For finance, TS2Vec embeddings concatenated with order-book features and fed to XGBoost is a reliable pipeline.
- **LSTM/GRU.** Still extensively used as crypto baselines; consistently beaten by N-HiTS/PatchTST/ModernTCN in controlled comparisons but cheaper to train and serve.

### 4. SOTA Techniques Specific to Crypto Markets

- **Funding-rate arbitrage on Binance perpetuals.** Delta-neutral cash-and-carry: long spot + short perp when funding > 0 (or reverse). He-Manela-Robles (arXiv 2212.06888v5, 2024) derives random-maturity no-arbitrage bounds and shows the deviation strategy yields high Sharpe even at top Binance taker fees. BitMEX 2025-Q3 derivatives report shows funding rates were positive ~92% of Q3 2025, anchored at the 0.01%/8h floor; BTC/ETH yields typically 5–25% APR neutral. Beware: spikes are short-lived because of arbitrage capital ceiling.
- **On-chain features.** **MVRV** (market cap / realized cap), **NVT** (market cap / on-chain volume), **SOPR** (spent-output profit ratio), **NUPL**, **HODL Waves**, exchange in/outflows, miner positions, ETF flows. Sources: Glassnode, CryptoQuant, Nansen, Dune. Most reliable for BTC/ETH macro; weak for altcoins. Exchange netflow leads price by 1–14 days in many studies; MVRV and NVT are cycle-position indicators, not timing signals.
- **Cross-exchange triangular and latency arb.** Requires colocation or proximity hosting; under heavy crowding outside top-3 venues. NautilusTrader's nanosecond clock and Rust core make it well-suited for the modeling side, but actual edge requires direct market access most retail users don't have.
- **Liquidation cascade prediction.** Open-interest concentration + funding-rate divergence + skew of the perp-spot basis. Useful as a tail-risk hedge, not as a primary alpha.
- **Stablecoin de-pegging strategies.** Ma-Zeng-Zhang (NBER 2025) model run risk; Curve LP depeg-detection (arXiv 2306.10612) gave ~5h advance warning of USDC March 2023 depeg. Mean-field game model (arXiv 2601.18991, 2026) calibrated to USDT/USDC events. Returns are episodic but high-Sharpe when triggered.
- **Sentiment.** FinBERT and FinGPT remain the workhorses; multimodal additions (TikTok video sentiment, arXiv 2508.15825, 2025) modestly improve out-of-sample. Twitter/X data: Ardia-Bluteau 2024 shows engagement (not just polarity) drives short-term price moves; pump-and-dump signals are persistent. PreBit (Mudassir et al., *Expert Systems w/ Apps* 2024) trades extreme moves with FinBERT embeddings and beats moving-average benchmarks.
- **DeFi.** LP IL-aware yield, MEV-aware execution (CoW, Flashbots), JIT liquidity. *Decentralised finance and automated market making* (J. Econ. Dyn. Control 2025) provides Cartea-style optimal control for AMM execution.

### 5. Evaluation Methodology That Survives 2025–2026 Critiques

- **Cross-validation.** Standard k-fold leaks. Use **purged k-fold with embargo** and **combinatorial purged CV (CPCV)** (Lopez de Prado, *Advances in Financial Machine Learning* 2018). For crypto: walk-forward with anchored or rolling origin, embargo ≥ horizon length.
- **Performance statistics.** **Probabilistic Sharpe Ratio (PSR)** and **Deflated Sharpe Ratio (DSR)** (Bailey & Lopez de Prado 2014) explicitly correct for selection bias from N trials and non-normal returns. **Minimum Track Record Length (MinTRL)** answers "how many months until I trust this Sharpe?". The probability of backtest overfitting (PBO) framework (Bailey-Borwein-Lopez de Prado-Zhu 2016) gives an O(N) overfitting probability.
- **Look-ahead and survivorship bias for foundation/LLM models.** **The 2025–2026 critiques are devastating and you must internalize them**:
  - **Profit Mirage** (Li et al., arXiv 2510.07920, 2025): leading LLM trading agents drop ~50% in returns once you trade *past* the LLM's knowledge cutoff. They release **FinLake-Bench** + **FactFin** counterfactual mitigation.
  - **Look-Ahead-Bench** (Benhenda, arXiv 2601.13770, 2026): formalizes lookahead measurement and provides PiT-Inference proprietary point-in-time LLMs.
  - **A Test of Lookahead Bias in LLM Forecasts** (Gao-Jiang-Yan, CUHK, Jan 2026, arXiv 2512.23847): introduces **Lookahead Propensity (LAP)** statistic that correlates with forecast accuracy precisely when leakage is present.
  - **Glasserman & Lin (2023)**: in-sample anonymization paradoxically improves news-sentiment trading performance because *distraction* dominates *look-ahead* before cutoff.
  - **A Fast and Effective Solution to Look-ahead Bias** (Merchant & Levy, U-Chicago, arXiv 2512.06607, 2026): logits arithmetic with "forget" and "retain" small models, claimed effective and cheap.
  - **TSFM-specific**: same problem applies — TimesFM/Chronos pretraining cutoffs (Wikipedia Nov 2023, EoY 2022 trends, mid-2024 LOTSA) overlap most published "out-of-sample" 2024 backtests.
- **Transaction cost modeling for crypto.** Maker/taker tiered fees (Binance VIP 0/1/...: 0.1%/0.08% spot, 0.02%/0.04% perp futures), funding payments every 8h, borrow rates for leverage, slippage modeled with square-root impact (Almgren) or via order-book replay. NautilusTrader supports tier-aware fee models and order-book L2 backtesting natively.

---

## PART 2 — AGENTS THAT GENERATE QUANTITATIVE STRATEGIES

### A) Agents for Alpha / Idea Generation

**The "alpha factory" or "alpha mining" paradigm**. The lineage from genetic programming (gplearn, AutoAlpha 2020) → reinforcement learning (AlphaGen, Yu et al. KDD 2023, arXiv 2306.12964 — RL with RPN tokens, the AlphaGen repo at `RL-MLDM/alphagen` is the de-facto open baseline) → generative-predictive nets (AlphaForge, AAAI 2025) → LLM-driven search (AlphaAgent KDD 2025, AlphaJungle MCTS arXiv 2505.11122). Each step expanded the search space at the cost of overfitting risk.

| Project | Authors / Venue | Core idea | Reported numbers |
|---|---|---|---|
| **AlphaGen** | Yu et al., KDD 2023 | PPO over RPN expression tokens | Significant IC uplift over genetic programming on CSI300 |
| **QuantFactor REINFORCE** | arXiv 2409.05144 | REINFORCE with variance bound, no critic | Lower variance than AlphaGen PPO |
| **AlphaForge** | Shi et al., AAAI 2025 (arXiv 2406.18394) | Generative-predictive net + dynamic weight adjustment | Outperforms AlphaGen on CSI300 IC; real-money trading uplift reported |
| **AlphaAgent** | Tang et al., KDD 2025 (arXiv 2502.16789) | LLM-driven mining w/ regularization to fight alpha decay | Beats RL/LLM baselines across bull/bear in CSI500 + S&P 500 over 4 years |
| **Navigating the Alpha Jungle** | Shi-Duan-Li, arXiv 2505.11122, 2025 | LLM + Monte-Carlo Tree Search | Better interpretability and Sharpe on CSI |
| **QuantAgent (Wang et al. 2024)** | arXiv 2402.03755 | Self-improving LLM with inner/outer loop critic | Holy-grail framing; modest empirical gains |
| **Alpha-GPT, AlphaGPT** | – | LLM-as-WorldQuant-Brain operator interface | Used in industry; few public benchmarks |

**WorldQuant Brain–style operator languages.** The standard operator set (`ts_rank`, `ts_mean`, `cross_sectional_rank`, `ts_corr`, `delta`, etc.) is the substrate; recent agents constrain LLM output to these grammars to keep generated alphas executable. Microsoft Qlib's `Alpha158` and `Alpha360` are the open-source equivalents and the universe where RD-Agent(Q), AlphaForge, AlphaAgent compete.

**FinMem, FinAgent, TradingAgents, FinCon, QuantAgent (HFT version).**
- **FinMem** (Yu et al., NeurIPS 2023 R0-FoMo workshop, arXiv 2311.13743): layered memory + character-design profiling.
- **FinAgent** (Zhang et al., KDD 2024, arXiv 2402.18485): multimodal (price, text, K-line images), tool augmentation, dual-level reflection. **92.27% return** on one dataset (with the look-ahead caveat above).
- **FinCon** (Yu et al., NeurIPS 2024, arXiv 2407.06567): manager-analyst hierarchy with verbal reinforcement.
- **TradingAgents** (Xiao et al. arXiv 2412.20138, popular open-source repo `TauricResearch/TradingAgents`): four analyst roles + bull/bear researchers + risk team + trader; LangGraph-based; supports OpenAI/Anthropic/Google/xAI/OpenRouter/Ollama. Trading-R1 (arXiv 2509.11420, 2025) extends with RL-over-reasoning.
- **QuantAgents (Li et al., arXiv 2510.04643, 2025)**: simulated-trading multi-agent system reporting **ARR 58.68%, SR 3.11, MDD 16.86%** on a beating benchmark — but again subject to look-ahead.
- **QuantAgent (Xiong et al., arXiv 2509.09995, 2025)**: HFT-tailored four-agent system (Indicator/Pattern/Trend/Risk), reports up to **80% directional accuracy** on 4h windows over 9–10 instruments including BTC and Nasdaq futures.

### B) Agents for Code Generation + Backtest Loops

- **RD-Agent / RD-Agent(Q)** (Microsoft Research, NeurIPS 2025, arXiv 2505.15155, repo `microsoft/RD-Agent`, 5.5K★, builds on `microsoft/Qlib` 24K★). The most rigorously validated agentic quant system in the literature. Decomposes pipeline into **Research → Development → Feedback** stages with a **multi-armed bandit scheduler**. The **Co-STEER** code-generation agent implements task code (factors and models). On CSI300 it achieves **2× annualized return vs Alpha158/TRA baselines using 70% fewer factors**, IC 0.0532, ARR 14.21% with GPT-4o-mini, and runs **under $10 per experiment**. RD-Agent has also been benchmarked on **MLE-bench** (75 ML competitions, Kaggle-style) — RD-Agent with o3+GPT-4.1 currently leads public results.
- **FinRobot** (Liu et al. AI4Finance group). Open-source LLM-based platform for financial tasks; less validated than RD-Agent but more accessible.
- **FinSearch / FinTeam** (arXiv 2502.15684, 2507.10448): multi-agent retrieval with temporal weighting; strong for news-driven research, weak for systematic alpha.
- **Iteration counts and success rates.** Across the available papers, ~10–30 iterations are typical for a single factor convergence in RD-Agent(Q); AlphaAgent reports "alpha decay" (factor IC degradation) is the binding constraint, not generation cost. Pass-rate-at-K of LLM-generated executable alpha factors is roughly 60–85% for GPT-4-class models with grammar constraints; fewer than 5% pass an OOS deflated-Sharpe gate without further regularization.

### C) Combined Research → Code → Live Pipelines

- **End-to-end reference architecture (RD-Agent(Q) blueprint).**
  1. **Specification agent** turns business goal + data schema into prompts.
  2. **Synthesis agent** generates hypotheses (factor expressions, model architectures).
  3. **Implementation agent (Co-STEER)** writes Python/Qlib code.
  4. **Validation agent** runs backtest, computes IC/IR/ARR/MDD.
  5. **Feedback agent** updates a knowledge forest of accepted/rejected hypotheses.
  6. **Bandit scheduler** allocates compute between factor mining and model search.
- **Roles in multi-agent systems**: Researcher, Engineer, Tester, Risk Reviewer, Portfolio Manager (TradingAgents), or Indicator/Pattern/Trend/Risk (QuantAgent HFT). Empirically, more agents help up to ~5–6 roles; beyond that, debate-quality decreases (per arXiv 2511.07784, "Can LLM Agents Really Debate?").
- **Numerai-style approach**: tournament of decentralized researchers submitting predictions on obfuscated features, ensembled by a meta-model. Different paradigm — humans and models compete for stake-weighted reward — but the philosophy of *aggressive ensembling + obfuscation against overfitting* is directly transferable.
- **Honest empirical takeaway.** When stripped of look-ahead bias (Profit Mirage tests, walk-forward starting *after* LLM training cutoff), most agent-generated trading strategies produce **near-zero alpha**. The exception is RD-Agent(Q)-style systems that generate **interpretable formulaic factors** evaluated on long, clean data with purged CV — there the generated factors *do* survive OOS, plausibly because the LLM is searching expression space rather than memorizing future returns. **This is the user's actionable signal: use agents to generate factor expressions and code; do NOT use them as on-line decision-makers without rigorous OOS gating.**

### D) Best Practices and Pitfalls

1. **Prevent p-hacking and overfitting.** Hard-cap candidate trials per universe per CV split, log every tried alpha, apply **deflated Sharpe** with the *true* trial count (RD-Agent's bandit makes this auditable). Use **CPCV with embargo ≥ horizon**. Hold out a final 6–12 months of *post-cutoff* data the agent never sees.
2. **Memory / experience accumulation.** RD-Agent's "knowledge forest" and FinMem's layered memory both work; the empirical evidence (FinAgent reflection module) shows ~5–15% lift from a working memory of past failed/successful factors. Persist across runs in vector DB (Chroma/Qdrant/Milvus).
3. **Cost economics.** RD-Agent(Q): **<$10 per discovered factor with GPT-4o-mini**; ~$30–80 with GPT-4o; substantially less with self-hosted Qwen-2.5/Llama-3-70B. Token spend per validated, OOS-passing strategy is realistically 5–50× the per-factor cost (10–50% retention rate).
4. **Validation gates (recommended stack).**
   - Gate 1: code executes, returns finite Sharpe.
   - Gate 2: in-sample IC > 0.02, IR > 0.3.
   - Gate 3: purged CPCV Sharpe > 1.0; turnover-aware net Sharpe > 0.5.
   - Gate 4: deflated Sharpe with full trial count > 0.
   - Gate 5: post-cutoff OOS holdout (6–12 months) net Sharpe > 0.3 with consistent sign.
   - Gate 6: regime-segmented Sharpe (bull/bear/chop, defined by 200d slope + RV percentile) > 0 in all regimes or honest acknowledgment of regime dependence.
5. **Concrete recommendations for NautilusTrader + Binance**: see the *Recommendations* section below.

---

## Critical Assessment of TimesFM for Crypto Trading

**Is TimesFM useful for crypto trading? Conditional yes — and only as one of several tools.**

- **Use it for:** zero-shot rapid prototyping of return forecasts on universes too large to model individually (e.g., 200-coin universe at 1h frequency); volatility-regime classification when paired with a calibrated quantile head; a "second opinion" feature input to gradient-boosted ensembles (which the Rahimikia 2025 study shows still dominate).
- **Don't use it for:** standalone trading signals on majors (Kronos and well-tuned PatchTST will beat zero-shot TimesFM); short-horizon (<5 min) microstructure (use OFI/book-pressure baselines instead); regime-shift backtests overlapping its pretraining window.

**Appropriate context lengths and frequencies:**
- **1-minute crypto bars**: max-context 1,024–2,048 (covers ~17h–34h) is the practical sweet spot; 16,384 (~11 days) is supported but inference cost dominates and effective horizon shrinks due to autoregressive error accumulation.
- **5-minute / 15-minute / 1-hour bars**: max-context 1,024–4,096 covers multiple seasonal cycles (intraday, weekly).
- **Daily**: 512–1,024 covers 2–4 years; usually enough.
- **Forecast horizon**: limit to ≤32 patches (≤512 steps) to avoid the autoregressive degradation; for longer needs, use the 30M continuous quantile head (up to 1,000 steps) and accept the calibration penalty.

**Integration as an agent-callable tool (recommended pattern):**

```python
# Conceptual sketch — TimesFM as a tool the agent can call from inside NautilusTrader strategy
class TimesFMTool:
    def __init__(self, checkpoint="google/timesfm-2.5-200m-pytorch"):
        self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(checkpoint)
        self.model.compile(timesfm.ForecastConfig(
            max_context=4096, max_horizon=64,
            normalize_inputs=True, use_continuous_quantile_head=True,
            force_flip_invariance=True, fix_quantile_crossing=True))

    def forecast(self, bars: list[float], horizon: int = 12):
        point, q = self.model.forecast(horizon=horizon, inputs=[np.array(bars)])
        return {
            "point": point[0].tolist(),
            "quantiles": q[0].tolist(),     # 10 quantiles 10..90
            "p_up_next": float((q[0,0,5:] > bars[-1]).mean()),  # crude probabilistic up-prob
        }
```

The tool sits in the strategy's `Cache`/`MessageBus` pipeline; the agent (RD-Agent-style) requests forecasts during research and generates `Strategy` subclasses that import this tool at decision time. **Critical**: at backtest time, ensure context windows do not extend past the bar timestamp (no leakage); NautilusTrader's event-driven engine enforces this automatically if you subscribe to `Bar` and read from rolling caches.

**Fine-tune or use Kronos?** For crypto specifically, **Kronos is currently the better-aligned default** (pretrained on K-lines, AAAI 2026, public repo `shiyu-coder/Kronos`, fine-tuning scripts released Aug 2025). Use TimesFM if you want a multi-frequency model that already handles non-K-line series (funding rates, on-chain MVRV time series, exchange-flow series); use Kronos for OHLCV forecasting itself. The pfnet `timesfm_fin` weights (continual-pretrained TimesFM on financial data including crypto) are a useful third option that bridges the two.

---

## Recommendations: A Concrete Build for NautilusTrader + Binance

Staged plan, decision-ready.

### Stage 0 (week 1–2): Data and Backtest Infrastructure
- Set up NautilusTrader's `BinanceDataClient` for spot + USDT-M perpetuals; use the order-book delta tutorial as your reference architecture.
- Ingest: 1m/5m/1h klines, perpetual funding rate history (3-day cumulative window), liquidations, open interest, basis spread, taker buy/sell volume.
- Augment with on-chain (Glassnode or CryptoQuant API): MVRV, NVT, exchange netflow, SOPR for BTC/ETH; CoinAPI or Tardis for L2 order books on top-20 USDT pairs.
- Build a **purged CPCV walk-forward framework** with embargo. Reserve a strict post-2025 holdout that no model — including any LLM agent — touches until final acceptance.
- Implement Binance VIP-tier-aware fee model + funding-payment cash flow + a square-root impact cost model in Nautilus's `BacktestEngine`.

### Stage 1 (week 3–6): Classical Baselines That Must Be Beaten
- Cross-sectional momentum (1d/7d/14d) on liquid USDT pairs.
- Funding-rate cash-and-carry on top-10 perps.
- HAR-RV volatility forecaster + GARCH(1,1) ensemble for risk parity weights.
- HRP portfolio over the strategy ensemble. Net-of-cost target Sharpe ≥ 1.0 on holdout.
- Microstructure: top-of-book OFI signal at 1m horizon on BTC/ETH.

These are your baselines. **Any TSFM- or agent-driven strategy must beat the HRP ensemble of these baselines net of costs on the post-cutoff holdout, by a deflated Sharpe margin, to be promoted to live.**

### Stage 2 (week 6–10): Foundation Model Layer
- Deploy **Kronos-base** (via `NeoQuasar/Kronos-base` HF repo) as your primary K-line forecaster. Fine-tune on Binance 1h USDT pair history through your training-cutoff date only. Use it as a feature generator (predicted return, predicted volatility, generated synthetic paths for stress-test), **not** as the trade decision.
- Run **TimesFM-2.5** in parallel with `max_context=2048`, `use_continuous_quantile_head=True`, on funding-rate and on-chain series (which Kronos isn't designed for).
- Feed Kronos and TimesFM outputs as additional features into a **CatBoost/LightGBM ensemble** (the Rahimikia 2025 result shows ensembles dominate).
- Validate via the 6-gate stack above.

### Stage 3 (week 10–16): Agentic Alpha Generation
- Deploy a **Microsoft RD-Agent(Q)** instance pointed at your Qlib-formatted Binance data. RD-Agent(Q) is the most validated quant-agent system in literature (NeurIPS 2025); use o3 or GPT-5-class for the Research stage, GPT-4.1 or DeepSeek-V3 for the Development (Co-STEER) stage. Budget: $10–50 per discovered alpha; expect 5–15% of alphas to survive Gate 5.
- Constrain the LLM to output **WorldQuant-style operator expressions** (Qlib's `Alpha158` operator set) — this is the empirical sweet spot for survivable alphas.
- Persist accepted alphas and failed-alpha signatures in a vector DB to avoid rediscovery.
- **Strict rule: the agent sees no data after your training cutoff.** Apply Profit Mirage / Look-Ahead-Bench best practices.

### Stage 4 (week 16+): Multi-Agent Trade Decisioning (optional, lower priority)
- Only after Stage 3 is delivering OOS-validated alpha, consider a **TradingAgents-style** wrapper (or QuantAgent for HFT) for ensemble decisioning. Treat it as a feature-engineering layer over the alpha bundle, with hard risk gates from NautilusTrader's RiskEngine.
- Default LLM: self-hosted Qwen-2.5-72B or Llama-3.3-70B-Instruct to control cost; benchmark against GPT-4o-mini quarterly.

### Validation Thresholds That Trigger Promotion / Demotion
| Gate | Threshold | Action if breached |
|---|---|---|
| Backtest CPCV Sharpe (gross) | ≥ 1.5 | Else discard |
| Net-of-cost Sharpe (Binance VIP-0) | ≥ 0.7 | Else discard |
| Deflated Sharpe (true trial count) | > 0 at 95% | Else discard |
| Post-cutoff holdout net Sharpe | ≥ 0.4 | Else paper-trade only |
| Live paper Sharpe (3 months) | ≥ 0.5 | Else demote |
| Live capital Sharpe (3 months) | ≥ 0.3 with MDD < 12% | Else flat / stop |

### What Would Change These Recommendations
- **If a peer-reviewed crypto-specific TSFM beats Kronos by ≥10% RankIC on Binance OOS data** → swap in. Watch arXiv q-fin.ST for 2026.
- **If RD-Agent(Q) is publicly extended to crypto/Qlib-Binance** → adopt the upstream version directly. Microsoft's Qlib roadmap mentions crypto, monitor `microsoft/Qlib` releases.
- **If your post-cutoff holdout net Sharpe falls below 0.3 across two consecutive quarters** → suspect crowding (Kronos and TimesFM are open-source), rotate to less common factor families (microstructure, on-chain) or proprietary alt-data.

---

## Caveats

1. **Look-ahead bias is the dominant risk for any pipeline that mixes pretrained foundation models with backtests covering 2020–2024.** TimesFM (Wikipedia cutoff Nov 2023, LOTSA mid-2024), Chronos (mid-2024), and most leading LLMs (GPT-4, Claude-3.5, Gemini) saw enormous amounts of crypto market commentary during pretraining. Profit Mirage (Li et al. 2025) and Look-Ahead-Bench (Benhenda 2026) show **~50% performance collapse** when this is corrected. **Treat all reported numbers in this report as upper bounds**; your own deflated-Sharpe-on-post-cutoff-holdout numbers are the only ones that matter.

2. **Many agent-system papers report optimistic numbers without this correction.** TradingAgents, FinAgent, QuantAgents (Li et al. 2025), and FinCon all report Sharpe > 2 and ARR > 30% on benchmarks where their underlying LLMs were trained on the period being tested. RD-Agent(Q) is the cleanest available result because it generates *factor expressions* rather than direct trade decisions, but even there the CSI300 benchmark window may overlap LLM pretraining.

3. **Crypto-specific TSFM evaluation is immature.** CTBench (NeurIPS 2025) is the first crypto-centric TSG benchmark and only covers generation, not forecasting. There is no equivalent of GIFT-Eval for crypto returns yet. Most published "crypto TSFM" results test on a handful of coins over ≤4 years and do not separate in-pretraining-window from post-cutoff.

4. **Reported Kronos numbers (+93% RankIC, +9% MAE volatility, +22% generative fidelity) are vs. baselines, not vs. simple HAR-RV/GARCH or vs. a well-tuned PatchTST**. Independent reproduction is recommended before betting capital.

5. **Liquidation cascade prediction, sentiment alpha, and stablecoin-depeg trades are episodic by nature**; backtest Sharpe is misleading because of the rare-event distribution. Use expected-shortfall and tail-loss metrics, not Sharpe alone.

6. **NautilusTrader is excellent infrastructure** (Rust core, nanosecond clock, research-live parity, native Binance Futures adapter) **but does not by itself solve modeling problems**. The hardest 80% of the work is data hygiene, walk-forward discipline, and cost modeling — none of which an agent will do for you reliably as of mid-2026.

7. **Regulatory and venue risk.** Binance funding-rate arbitrage, leverage limits, and account categorization (US vs non-US) materially affect strategy economics. Verify before sizing.

8. **The 2026-vintage foundation-model and agent-quant literature is evolving fast.** Re-check arXiv q-fin and the NeurIPS 2025 "BERT² moment" workshop output every quarter; any specific architectural recommendation here may have a 6–12 month half-life.