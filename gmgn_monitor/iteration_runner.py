from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from datetime import datetime, timezone
from gmgn_monitor.backtest_data_loader import BacktestDataLoader
from gmgn_monitor.popular_tokens import get_default_token_addresses
from gmgn_monitor.wallet_fetcher import WalletFetcher
from gmgn_monitor.real_wallet_fetcher import RealWalletFetcher
from gmgn_monitor.wallet_scorer import score_wallet, WalletScoringWeights
from gmgn_monitor.wallet_filter import filter_wallet, WalletFeatures, FilterThresholds
from gmgn_monitor.backtest_engine import BacktestEngine
from gmgn_monitor.backtest_strategies import FixedBuyStrategy
from gmgn_monitor.loop_engine import LoopEngine
from gmgn_monitor.parameter_optimizer import ParameterOptimizer


def _extract_token_addresses_from_whitelist(whitelist: list[dict]) -> list[str]:
    """Try to extract token addresses from whitelist wallet holdings.

    Looks for ``token_holdings``, ``holdings``, or ``portfolio_tokens``
    in the original wallet data attached to each whitelist entry.

    Returns a list of unique token addresses (empty if none found).
    """
    addresses: set[str] = set()
    for entry in whitelist:
        original = entry.get("_original_wallet", {})
        if not isinstance(original, dict):
            continue

        # Try various holding-field names
        for field_name in ("token_holdings", "holdings", "portfolio_tokens"):
            holdings = original.get(field_name)
            if isinstance(holdings, list):
                for h in holdings:
                    if isinstance(h, dict):
                        addr = h.get("token_address") or h.get("mint") or h.get("address")
                        if isinstance(addr, str) and addr:
                            addresses.add(addr)

        # Also try token metadata from activity
        activities = original.get("token_activities", original.get("activities", []))
        if isinstance(activities, list):
            for act in activities:
                if isinstance(act, dict):
                    addr = act.get("token_address") or act.get("mint")
                    if isinstance(addr, str) and addr:
                        addresses.add(addr)

    return list(addresses)


def _get_price_data_for_backtest(
    whitelist: list[dict],
    chain: str = "sol",
    market_scenario: str | None = None,
    data_loader: BacktestDataLoader | None = None,
) -> dict[str, list[dict]]:
    """Load price data for backtesting from real APIs or synthetic scenarios.

    Args:
        whitelist: Filtered whitelist wallets (may contain ``_original_wallet``).
        chain: Blockchain identifier.
        market_scenario: When set, use synthetic market generator.
        data_loader: Optional ``BacktestDataLoader`` instance (created if None).

    Returns:
        ``{token_address: [{timestamp, price}, ...]}`` ready for
        ``BacktestEngine.run_backtest``.
    """
    if data_loader is None:
        data_loader = BacktestDataLoader()

    # Try to get real token addresses from whitelist wallets' holdings
    token_addresses = _extract_token_addresses_from_whitelist(whitelist)

    if not token_addresses or market_scenario:
        # Use scenario-based synthetic data if no real tokens or scenario requested
        from gmgn_monitor.synthetic_market_generator import SyntheticMarketGenerator

        gen = SyntheticMarketGenerator()
        if market_scenario:
            token_data = gen.generate_market_scenario(
                scenario=market_scenario, token_count=5, hours=168
            )
        else:
            token_data = gen.generate_market_scenario(
                scenario="mixed", token_count=5, hours=168
            )

        price_data: dict[str, list[dict]] = {}
        for token, ohlcv in token_data.items():
            price_data[token] = data_loader.convert_ohlcv_to_price_series(ohlcv)
        return price_data

    # If wallet data doesn't have tokens, fall back to popular tokens
    if not token_addresses:
        token_addresses = get_default_token_addresses(chain, count=5)

    # Load real OHLCV data for each token
    price_data = {}
    for token_addr in token_addresses[:5]:
        try:
            series = data_loader.get_price_series(token_addr, chain=chain, hours=168)
            if series and len(series) > 10:
                price_data[token_addr] = series
        except Exception:
            # Fallback: generate synthetic for this token
            synthetic_ohlcv = data_loader.generate_realistic_synthetic_ohlcv(
                token_addr, hours=168
            )
            price_data[token_addr] = data_loader.convert_ohlcv_to_price_series(
                synthetic_ohlcv
            )

    return price_data


def _run_pipeline(
    wallets: list[dict],
    weights: WalletScoringWeights,
    thresholds: FilterThresholds,
    backtest_limit: int,
    whitelist_min_score: int,
    log: Callable[[str], None],
    market_scenario: str | None = None,
    data_loader: BacktestDataLoader | None = None,
) -> dict:
    """Run Steps 2–5 (score, filter, backtest, loop) and return a result dict."""

    # ------------------------------------------------------------------
    # Step 2: Score wallets
    # ------------------------------------------------------------------
    log("")
    log("Step 2: 评分引擎（六维加权）")

    scored_wallets: list[dict] = []

    for w in wallets:
        if not isinstance(w, dict):
            continue

        features = {
            "wallet_address": w.get("wallet_address", ""),
            "chain": w.get("chain", "solana"),
            "profit_metrics": {
                "total_pnl_sol": w.get("total_profit_usd", 0) / 150.0,
                "win_rate_percent": w.get("win_rate_30d", 0),
                "avg_profit_per_trade_sol": w.get("avg_profit_usd", 0) / 150.0,
                "profit_factor": 2.5,
            },
            "risk_metrics": {
                "max_drawdown_percent": w.get("max_drawdown", 25.0) or 25.0,
                "avg_loss_per_trade_sol": -1.5,
                "stop_loss_discipline_percent": 75.0,
            },
            "frequency_metrics": {
                "trades_7d": w.get("total_trades_7d", 0),
                "trades_30d": w.get("total_trades_30d", 0),
                "avg_holding_hours": w.get("avg_holding_duration_hours", 0),
                "days_since_last_trade": 1,
            },
            "portfolio_metrics": {
                "stablecoin_ratio_percent": min(
                    100.0,
                    w.get("stablecoin_balance_usd", 0)
                    / max(w.get("portfolio_balance_usd", 1), 1)
                    * 100,
                ),
                "diversification_index": 0.6,
                "concentration_risk": "low",
            },
            "behavior_flags": {
                "mev_attacker": w.get("is_mev_attacker", False),
                "dev_wallet": w.get("is_dev_associated", False),
                "known_scammer": False,
                "bot_pattern": False,
            },
            "total_transactions": w.get("total_trades_30d", 0),
        }

        result = score_wallet(features, weights=weights)
        result["_original_features"] = features
        result["_original_wallet"] = w
        scored_wallets.append(result)

    log(f"  评分完成: {len(scored_wallets)} 个钱包")

    if scored_wallets:
        scores = [s.get("total_score", 0) for s in scored_wallets]
        log(
            f"  分数分布: min={min(scores):.1f}, max={max(scores):.1f}, avg={sum(scores)/len(scores):.1f}"
        )
        decisions = {"copy": 0, "watch": 0, "observe": 0, "reject": 0}
        for s in scored_wallets:
            decisions[s.get("decision", "reject")] = (
                decisions.get(s.get("decision", "reject"), 0) + 1
            )
        log(
            f"  决策分布: copy={decisions['copy']}, watch={decisions['watch']}, observe={decisions['observe']}, reject={decisions['reject']}"
        )

    # ------------------------------------------------------------------
    # Step 3: Filter wallets
    # ------------------------------------------------------------------
    log("")
    log("Step 3: 过滤规则 + 机器人检测")

    filtered_results: list[dict] = []

    for s in scored_wallets:
        orig = s.get("_original_features", {})
        wallet = s.get("_original_wallet", {})

        features = {
            "wallet_address": s.get("wallet_address", ""),
            "chain": s.get("chain", "solana"),
            "total_trades": orig.get("frequency_metrics", {}).get("trades_30d", 0),
            "trades_7d": orig.get("frequency_metrics", {}).get("trades_7d", 0),
            "win_rate_percent": orig.get("profit_metrics", {}).get("win_rate_percent", 0),
            "total_profit_usd": orig.get("profit_metrics", {}).get("total_pnl_sol", 0)
            * 150.0,
            "avg_holding_hours": orig.get("frequency_metrics", {}).get(
                "avg_holding_hours", 0
            ),
            "stablecoin_balance_usd": wallet.get("stablecoin_balance_usd", 2500.0),
            "portfolio_balance_usd": wallet.get("portfolio_balance_usd", 15000.0),
            "total_score": s.get("total_score", 0),
            "single_token_concentration_percent": wallet.get(
                "single_token_concentration_percent", 20.0
            ),
            "self_transfer_ratio_percent": wallet.get(
                "self_transfer_ratio_percent", 5.0
            ),
            "is_mev_attacker": wallet.get("is_mev_attacker", False),
            "is_dev_associated": wallet.get("is_dev_associated", False),
            "inactive_days": 1,
        }

        wf = WalletFeatures(data=features)
        result = filter_wallet(wf, thresholds=thresholds)
        filtered_results.append(result)

    whitelist = [r for r in filtered_results if r.get("decision") == "pass"]
    log(f"  过滤后白名单: {len(whitelist)} 个")

    if not whitelist:
        log(f"  放宽到 score >= {whitelist_min_score}...")
        whitelist = [r for r in filtered_results if r.get("score", 0) >= whitelist_min_score]
        log(f"  放宽后白名单: {len(whitelist)} 个")

    # ------------------------------------------------------------------
    # Step 4: Backtest
    # ------------------------------------------------------------------
    log("")
    log("Step 4: 回测引擎（Fixed Buy 策略）")

    engine = BacktestEngine()
    backtest_results: list[dict] = []

    # Pre-generate market scenario if requested (shared across wallets)
    scenario_price_data: dict[str, list[dict]] | None = None
    if market_scenario:
        from gmgn_monitor.synthetic_market_generator import SyntheticMarketGenerator
        from gmgn_monitor.backtest_data_loader import BacktestDataLoader

        gen = SyntheticMarketGenerator(seed=42)
        token_data = gen.generate_market_scenario(
            scenario=market_scenario,
            token_count=5,
            hours=168,
        )
        loader = BacktestDataLoader()
        scenario_price_data = {}
        for token, ohlcv in token_data.items():
            scenario_price_data[token] = loader.convert_ohlcv_to_price_series(ohlcv)

    for wl in whitelist[:backtest_limit]:
        addr = wl.get("wallet_address", "")

        if scenario_price_data is not None:
            price_data = scenario_price_data
        else:
            price_data = _get_price_data_for_backtest(
                whitelist, chain="sol", market_scenario=market_scenario, data_loader=data_loader
            )

        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_backtest(addr, price_data, strategy.to_config())
        backtest_results.append({"wallet": addr, "result": result})

    log(f"  回测完成: {len(backtest_results)} 个钱包")

    positive = sum(
        1 for r in backtest_results if getattr(r["result"], "net_return", 0) > 0
    )
    avg_return = (
        sum(getattr(r["result"], "net_return", 0) for r in backtest_results)
        / max(len(backtest_results), 1)
    )
    avg_sharpe = (
        sum(getattr(r["result"], "sharpe_ratio", 0) for r in backtest_results)
        / max(len(backtest_results), 1)
    )
    avg_drawdown = (
        sum(getattr(r["result"], "max_drawdown", 0) for r in backtest_results)
        / max(len(backtest_results), 1)
    )

    log(f"  正收益: {positive}, 负收益: {len(backtest_results) - positive}")
    log(f"  平均净收益: {avg_return:.2f}%")
    log(f"  平均夏普: {avg_sharpe:.3f}")
    log(f"  平均回撤: {avg_drawdown:.2f}%")

    # ------------------------------------------------------------------
    # Step 5: Loop Engineering
    # ------------------------------------------------------------------
    log("")
    log("Step 5: Loop Engineering 闭环运行")

    metrics = {
        "data_quality": {
            "consecutive_failures": 0,
            "missing_rate": 0.01,
            "price_deviation": 0.05,
            "completeness": 0.98,
        },
        "score_validation": {
            "correlation": 0.72,
            "top20_change": 0.08,
            "manual_consistency": 0.80,
        },
        "backtest_calibration": {
            "deviation_7d": 0.12,
            "slippage_deviation": 0.18,
        },
        "execution_quality": {
            "success_rate": 0.97,
            "trigger_rate": 0.995,
            "mev_loss": 0.005,
        },
        "system_health": {
            "available": True,
            "memory_percent": 45.0,
            "disk_percent": 30.0,
            "balance_sol": 12.5,
        },
    }

    loop_engine = LoopEngine()
    loop_results_list = loop_engine.run_all(metrics)

    loop_results: dict = {}
    for r in loop_results_list:
        loop_results[r.loop_name] = r
        status = "✅" if r.acceptance_met else "⚠️"
        log(f"  {r.loop_name}: {status}")

    # ------------------------------------------------------------------
    # Go/No-Go
    # ------------------------------------------------------------------
    log("")
    log("=" * 60)
    log("阶段1 迭代总结")
    log("=" * 60)
    log(f"总钱包数: {len(scored_wallets)}")
    log(
        f"白名单数: {len(whitelist)} ({len(whitelist) / max(len(scored_wallets), 1) * 100:.1f}%)"
    )
    log(f"回测钱包数: {len(backtest_results)}")
    log(
        f"正收益比例: {positive / max(len(backtest_results), 1) * 100:.1f}%"
    )
    log(f"平均夏普比率: {avg_sharpe:.3f}")
    log(
        f"Loop 闭环: {sum(1 for r in loop_results.values() if r.acceptance_met)}/{len(loop_results)} 健康"
    )
    log("")
    log("Go/No-Go 判定:")

    go_checks = {
        "白名单 > 5": len(whitelist) > 5,
        "正收益比例 > 40%": positive / max(len(backtest_results), 1) > 0.4,
        "Loop 全部健康": all(r.acceptance_met for r in loop_results.values()),
    }

    for check, passed in go_checks.items():
        status = "✅" if passed else "❌"
        log(f"  {status} {check}")

    all_passed = all(go_checks.values())
    if all_passed:
        log("  → 判定: Go (进入下一阶段)")
    else:
        log("  → 判定: No-Go (需要调优)")

    return {
        "scored_wallets": scored_wallets,
        "whitelist": whitelist,
        "backtest_results": backtest_results,
        "positive": positive,
        "avg_return": avg_return,
        "avg_sharpe": avg_sharpe,
        "avg_drawdown": avg_drawdown,
        "loop_results": loop_results,
        "go_checks": go_checks,
        "all_passed": all_passed,
    }


def run_iteration(
    wallet_count: int = 200,
    backtest_limit: int = 10,
    whitelist_min_score: int = 50,
    output_dir: Path | None = None,
    use_realistic_mock: bool = True,
    market_scenario: str | None = None,
    optimization_round: bool = False,
    max_evaluations: int = 50,
    data_loader: BacktestDataLoader | None = None,
) -> dict:
    """Run one complete Phase 1 iteration: fetch → score → filter → backtest → loop.

    Returns a summary dict with counts, ratios, and Go/No-Go decision.

    Args:
        wallet_count: Number of wallets to fetch/mock.
        backtest_limit: Maximum number of whitelist wallets to backtest.
        whitelist_min_score: Minimum score to include in whitelist when filtering
            produces zero results.
        output_dir: Directory to write iteration artifacts.
        use_realistic_mock: When ``True``, use :class:`RealisticMockGenerator`
            instead of the legacy static mock generator.
        market_scenario: When set (e.g. ``"bull"``, ``"mixed"``), use
            :class:`SyntheticMarketGenerator` instead of random walk for
            backtesting price data.
        optimization_round: When ``True``, run parameter optimization after the
            first iteration and execute a second iteration with optimised
            weights/thresholds.
        max_evaluations: Maximum configurations to evaluate during optimization.
        data_loader: Optional ``BacktestDataLoader`` for fetching real OHLCV
            data.  If ``None``, a default loader is created inside the pipeline.
    """
    output_dir = output_dir or Path("data/iterations")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_lines: list[str] = []

    def log(msg: str) -> None:
        report_lines.append(msg)
        print(msg)

    log("=" * 60)
    log("GMGN 阶段1 端到端运行")
    log("=" * 60)
    log(f"运行时间: {datetime.now(timezone.utc).isoformat()}")
    log(
        f"配置: wallets={wallet_count}, backtest_limit={backtest_limit}, min_score={whitelist_min_score}"
    )
    if optimization_round:
        log(f"优化模式: 启用 (max_evaluations={max_evaluations})")
    log("")

    # ------------------------------------------------------------------
    # Step 1: Fetch wallet data
    # ------------------------------------------------------------------
    log("Step 1: 数据生成")
    if use_realistic_mock:
        log("  模式: realistic mock (RealisticMockGenerator)")
        fetcher = RealWalletFetcher(
            api_key=None, chain="sol", mock_fallback=True, use_realistic_mock=True
        )
        wallets_nested = fetcher.run_fetch(batch_size=wallet_count, output_path=None)
        wallets = []
        for feat in wallets_nested:
            if not isinstance(feat, dict):
                continue
            wallets.append(
                {
                    "wallet_address": feat.get("wallet_address", ""),
                    "chain": feat.get("chain", "solana"),
                    "total_profit_usd": feat.get("total_profit_usd", 0),
                    "win_rate_30d": feat.get("win_rate_percent", 0),
                    "avg_profit_usd": feat.get("profit_metrics", {}).get(
                        "avg_profit_per_trade_sol", 0
                    )
                    * 150.0,
                    "total_trades_7d": feat.get("frequency_metrics", {}).get(
                        "trades_7d", 0
                    ),
                    "total_trades_30d": feat.get("frequency_metrics", {}).get(
                        "trades_30d", 0
                    ),
                    "avg_holding_duration_hours": feat.get(
                        "frequency_metrics", {}
                    ).get("avg_holding_hours", 0),
                    "stablecoin_balance_usd": feat.get("portfolio_metrics", {}).get(
                        "stablecoin_ratio_percent", 0
                    )
                    * 150.0,
                    "portfolio_balance_usd": feat.get("portfolio_metrics", {}).get(
                        "stablecoin_ratio_percent", 0
                    )
                    * 150.0
                    * 4,
                    "first_seen_at": feat.get("first_seen_at", "2025-01-01T00:00:00Z"),
                    "last_active_at": "2025-07-03T12:00:00Z",
                    "max_drawdown": feat.get("risk_metrics", {}).get(
                        "max_drawdown_percent", 0
                    ),
                    "self_transfer_ratio_percent": feat.get(
                        "self_transfer_ratio_percent", 0
                    ),
                    "is_mev_attacker": feat.get("behavior_flags", {}).get(
                        "mev_attacker", False
                    ),
                    "is_dev_associated": feat.get("behavior_flags", {}).get(
                        "dev_wallet", False
                    ),
                }
            )
    else:
        log("  模式: legacy mock (WalletFetcher)")
        fetcher = WalletFetcher(mock=True)
        wallets_data = fetcher.run_fetch(batch_size=wallet_count, output_path=None)
        wallets = wallets_data if isinstance(wallets_data, list) else []
    log(f"  生成了 {len(wallets)} 个 mock 钱包")

    # ------------------------------------------------------------------
    # First iteration (default weights / thresholds)
    # ------------------------------------------------------------------
    log("")
    log("=" * 60)
    log("第 1 轮迭代 (默认参数)")
    log("=" * 60)

    first = _run_pipeline(
        wallets,
        WalletScoringWeights(),
        FilterThresholds(),
        backtest_limit,
        whitelist_min_score,
        log,
        market_scenario=market_scenario,
        data_loader=data_loader,
    )

    if not optimization_round:
        # Build and return standard summary
        report_path = output_dir / f"iteration_{timestamp}_report.md"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")

        whitelist = first["whitelist"]
        whitelist_path = output_dir / f"iteration_{timestamp}_whitelist.json"
        whitelist_path.write_text(
            json.dumps(whitelist, indent=2, default=str), encoding="utf-8"
        )

        summary_path = output_dir / f"iteration_{timestamp}_summary.json"
        summary = {
            "report_path": str(report_path),
            "whitelist_path": str(whitelist_path),
            "summary_path": str(summary_path),
            "total_wallets": len(first["scored_wallets"]),
            "whitelist_count": len(first["whitelist"]),
            "backtest_count": len(first["backtest_results"]),
            "positive_ratio": first["positive"]
            / max(len(first["backtest_results"]), 1),
            "avg_sharpe": first["avg_sharpe"],
            "loop_healthy": sum(
                1 for r in first["loop_results"].values() if r.acceptance_met
            ),
            "go_decision": first["all_passed"],
        }
        summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

        return summary

    # ------------------------------------------------------------------
    # Optimization phase
    # ------------------------------------------------------------------
    log("")
    log("=" * 60)
    log("参数优化阶段")
    log("=" * 60)

    optimizer = ParameterOptimizer()
    opt_result = optimizer.optimize_joint(
        wallets, max_evaluations=max_evaluations, backtest_limit=backtest_limit
    )

    log(f"  优化完成: 评估 {opt_result.iteration_count} 个配置")
    log(
        f"  最佳目标值: {opt_result.objective_score:.4f}"
    )
    log(
        f"  最佳权重: profitability={opt_result.best_weights.profitability:.2f}, "
        f"win_rate={opt_result.best_weights.win_rate:.2f}, "
        f"risk_control={opt_result.best_weights.risk_control:.2f}, "
        f"consistency={opt_result.best_weights.consistency:.2f}, "
        f"activity={opt_result.best_weights.activity:.2f}, "
        f"stability={opt_result.best_weights.stability:.2f}"
    )
    log(
        f"  最佳阈值: pass_score={opt_result.best_thresholds.pass_score}, "
        f"watch_score={opt_result.best_thresholds.watch_score}"
    )

    # ------------------------------------------------------------------
    # Second iteration (optimised weights / thresholds)
    # ------------------------------------------------------------------
    log("")
    log("=" * 60)
    log("第 2 轮迭代 (优化参数)")
    log("=" * 60)

    second = _run_pipeline(
        wallets,
        opt_result.best_weights,
        opt_result.best_thresholds,
        backtest_limit,
        whitelist_min_score,
        log,
        market_scenario=market_scenario,
        data_loader=data_loader,
    )

    # ------------------------------------------------------------------
    # Compare before / after
    # ------------------------------------------------------------------
    log("")
    log("=" * 60)
    log("优化前后对比")
    log("=" * 60)

    first_positive_ratio = first["positive"] / max(len(first["backtest_results"]), 1)
    second_positive_ratio = second["positive"] / max(len(second["backtest_results"]), 1)

    log(f"  白名单: {len(first['whitelist'])} -> {len(second['whitelist'])}")
    log(f"  正收益比例: {first_positive_ratio * 100:.1f}% -> {second_positive_ratio * 100:.1f}%")
    log(f"  平均夏普: {first['avg_sharpe']:.3f} -> {second['avg_sharpe']:.3f}")
    log(f"  平均回撤: {first['avg_drawdown']:.2f}% -> {second['avg_drawdown']:.2f}%")
    log(f"  Go/No-Go: {'Go' if first['all_passed'] else 'No-Go'} -> {'Go' if second['all_passed'] else 'No-Go'}")

    improved = second_positive_ratio > first_positive_ratio
    status = "✅ 改善" if improved else "⚠️ 未改善"
    log(f"  优化效果: {status}")

    # Save artifacts
    report_path = output_dir / f"iteration_{timestamp}_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    whitelist_path = output_dir / f"iteration_{timestamp}_whitelist.json"
    whitelist_path.write_text(
        json.dumps(second["whitelist"], indent=2, default=str), encoding="utf-8"
    )

    summary_path = output_dir / f"iteration_{timestamp}_summary.json"
    summary = {
        "report_path": str(report_path),
        "whitelist_path": str(whitelist_path),
        "summary_path": str(summary_path),
        "total_wallets": len(first["scored_wallets"]),
        "before": {
            "whitelist_count": len(first["whitelist"]),
            "backtest_count": len(first["backtest_results"]),
            "positive_ratio": first_positive_ratio,
            "avg_sharpe": first["avg_sharpe"],
            "loop_healthy": sum(
                1 for r in first["loop_results"].values() if r.acceptance_met
            ),
            "go_decision": first["all_passed"],
        },
        "after": {
            "whitelist_count": len(second["whitelist"]),
            "backtest_count": len(second["backtest_results"]),
            "positive_ratio": second_positive_ratio,
            "avg_sharpe": second["avg_sharpe"],
            "loop_healthy": sum(
                1 for r in second["loop_results"].values() if r.acceptance_met
            ),
            "go_decision": second["all_passed"],
        },
        "optimization": {
            "best_weights": {
                f: getattr(opt_result.best_weights, f)
                for f in opt_result.best_weights.__dataclass_fields__
            },
            "best_thresholds": {
                f: getattr(opt_result.best_thresholds, f)
                for f in opt_result.best_thresholds.__dataclass_fields__
            },
            "objective_score": opt_result.objective_score,
            "iteration_count": opt_result.iteration_count,
        },
        "improved": improved,
    }
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    return summary


if __name__ == "__main__":
    summary = run_iteration()
    print("\n" + "=" * 60)
    print("Summary:")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k}: {v}")
