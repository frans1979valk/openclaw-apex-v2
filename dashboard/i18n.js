/**
 * OpenClaw Apex — Translation file (i18n)
 *
 * HOW TO ADD A LANGUAGE:
 * 1. Copy the "en" block below
 * 2. Add a new key (e.g. "de" for German, "es" for Spanish)
 * 3. Translate all values
 * 4. Change LANG below to your language code
 *
 * HOW IT WORKS:
 * Call t("key") anywhere in the dashboard HTML to get the translated string.
 * Example: t("bot_start") returns "Bot starten" (nl) or "Start bot" (en)
 */

// Language: saved in localStorage, or auto-detected from browser (default: "nl")
let LANG = (function() {
  const saved = localStorage.getItem("oc_lang");
  if (saved && ["nl","en"].includes(saved)) return saved;
  const browser = (navigator.language || "").slice(0, 2).toLowerCase();
  return browser === "en" ? "en" : "nl";
})();

const TRANSLATIONS = {

  nl: {
    // --- Page titles ---
    title_live_signals:       "Live Signalen",
    title_setup_intelligence: "Setup Intelligence",
    title_bot_positions:      "Bot Posities",
    title_sterk_quality:      "STERK Kwaliteit",
    title_chart:              "Chart",

    // --- Navigation ---
    nav_live:       "⚡ Live",
    nav_setup:      "📊 Setup Intel",
    nav_chart:      "📈 Chart",
    nav_positions:  "🤖 Bot",
    nav_quality:    "📉 STERK",
    nav_logout:     "Uitloggen",
    nav_back:       "← Terug",
    nav_dashboard:  "Dashboard",
    nav_setup_intel:"← Setup Intel",

    // --- Status bar ---
    btc_regime:         "BTC Regime",
    active_signals:     "Actief signaal",
    sterk_active:       "STERK actief",
    coins_monitored:    "Coins gemonitord",
    bot_status:         "Bot status",
    open_slots:         "Open slots",
    updated:            "Bijgewerkt",
    connected:          "Verbonden",

    // --- Filters ---
    filter_label:       "Filter:",
    filter_all:         "Alles",
    filter_signal:      "Met signaal",
    filter_sterk:       "STERK + TOESTAAN",
    refresh:            "Nu vernieuwen",
    auto_refresh:       "Auto-refresh over",
    auto_refresh_unit:  "s",

    // --- Table headers ---
    col_coin:           "Coin",
    col_price:          "Live prijs",
    col_rsi:            "RSI (1h)",
    col_macd:           "MACD",
    col_adx:            "ADX",
    col_ema:            "EMA regime",
    col_signal:         "Signaal nu",
    col_verdict:        "Verdict",
    col_score:          "Score",
    col_win_pct:        "Win%",
    col_avg_pnl:        "Gem. +1h",
    col_data_from:      "Data van",
    col_last_signal:    "Laatste signaal",
    col_entry:          "Entry prijs",
    col_exit:           "Exit prijs",
    col_stake:          "Inzet",
    col_duration:       "Duur",
    col_gross_pnl:      "Bruto P&L",
    col_net_pnl:        "Netto P&L",
    col_fee:            "Kosten",
    col_reason:         "Reden",
    col_trades:         "Trades",
    col_winrate:        "Winrate",
    col_win_hist:       "Win% historisch",
    col_avg_hist:       "Gem. P&L hist.",
    col_net_trade:      "Gem. netto/trade",
    col_total_net:      "Totaal netto",
    col_chance:         "Kans",
    col_expected:       "Verwachte beweging",
    col_market:         "Marktconditie",
    col_status:         "Status",
    col_setup_score:    "Setup score",
    col_n_hist:         "Historisch (n)",

    // --- Signals ---
    no_signal:          "Geen signaal",
    signal_active:      "Nu actief",
    time_recent:        "recent",
    time_h_old:         "u oud",
    time_d_old:         "d oud",
    hours_ago:          "h geleden",
    days_ago:           "d geleden",
    last_signal_tooltip: "Hoe lang geleden het signaal voor het laatste actief was",

    // --- MACD labels ---
    macd_neutral:       "neutraal",

    // --- Verdicts ---
    verdict_sterk:        "STERK",
    verdict_toestaan:     "TOESTAAN",
    verdict_toestaan_zwak: "TOESTAAN_ZWAK",
    verdict_skip:         "SKIP",

    // --- Bot controls ---
    bot_start:          "Bot starten",
    bot_stop:           "Bot stoppen",
    bot_running:        "Bot draait — wacht op een STERK signaal.",
    bot_start_prompt:   "Start de bot via de knop rechtsboven.",
    test_trade:         "Test trade",

    // --- Chart ---
    chart_error:        "Chart fout:",
    chart_hover:        "Hover over grafiek voor OHLCV waarden...",
    show_setup_markers: "Setup Intel STERK/TOESTAAN momenten tonen",
    show_bot_trades:    "Testbot trades tonen",
    coin_placeholder:   "Zoek coin...",
    coin_hint:          "Selecteer een coin uit de dropdown of voer een symbool in.",
    coin_fill:          "Vul een symbol in.",
    open_chart:         "Open grafiek",

    // --- Loading / errors ---
    loading:            "Laden...",
    loading_price:      "laden...",
    error:              "Fout",
    error_bot_toggle:   "Fout bij bot toggle: ",
    error_loading:      "Fout bij laden:",
    no_signals_filter:  "Geen signalen gevonden voor dit filter.",
    no_data_winrate:    "Geen historische winrate-data beschikbaar voor deze setup.",
    no_data_pnl:        "Geen gemiddelde P&L data beschikbaar voor deze setup.",

    // --- Detail panel: live signals ---
    dp_indicators_from:   "Indicators van:",
    dp_current_indicators:"Actuele indicatoren (1h)",
    dp_live_price:        "Live prijs",
    dp_macd_hist:         "MACD histogram",
    dp_bb_position:       "BB positie",
    dp_volume_ratio:      "Volume ratio",
    dp_volume_avg:        "x gem.",
    dp_historical:        "Historische kwaliteit",
    dp_no_signal:         "geen signaal",
    dp_win_pct_1h:        "Win% (1h)",
    dp_avg_pnl_1h:        "Gem. P&L (1h)",
    dp_n_trades:          "Aantal trades (n)",
    dp_edge_strength:     "Edge strength",
    dp_regime_fit:        "Regime fit",

    // --- Interpretation texts ---
    interp_signal:        "Signaal:",
    interp_hist_intro:    "Historisch haalt dit signaal op",
    interp_win_chance:    "winkans",
    interp_with_avg:      "met gemiddeld",
    interp_after_1h:      "na 1 uur",
    interp_based_on:      "gebaseerd op",
    interp_hist_trades:   "historische trades",
    interp_sterk:         "Sterke setup — dit is een van de beste setups in het systeem.",
    interp_toestaan:      "Toegestaan — solide setup, de bot mag hier actie op ondernemen.",
    interp_zwak:          "Zwak — marginale setup, bot handelt hier niet op.",
    interp_skip:          "Skip — negatieve verwachting, bot slaat dit over.",
    interp_no_signal:     "Geen actief signaal op dit moment.",
    interp_bot_monitors:  "De bot monitort deze coin maar onderneemt nu geen actie.",

    // --- STERK Quality summaries ---
    summary_good:       "De STERK adviezen werken goed. Meer dan 60% van de trades was winstgevend en het totaalresultaat is positief.",
    summary_ok:         "De STERK adviezen werken redelijk. De winrate is acceptabel en het resultaat staat in de plus.",
    summary_mixed:      "Gemengd beeld: de winrate is redelijk maar de fees en verliezende trades wegen zwaarder. Meer data nodig.",
    summary_early:      "De STERK adviezen presteren nog niet zoals verwacht. Meer data verzamelen voor een betrouwbaar beeld.",

    // --- Misc ---
    download_csv:       "Download als CSV",
    custom_symbol:      "Eigen symbool, bijv. APEUSDT",
    regime_bull:        "stijgende markt (BULL)",
    regime_bear:        "dalende markt (BEAR)",
    close:              "Sluiten",

    // --- Setup Intelligence page ---
    si_sort_label:            "Sorteer:",
    si_sort_avg_pnl:          "Gem. P&L 1h",
    si_sort_count:            "Aantal (n)",
    si_th_signal:             "Signaal",
    si_last_update_prefix:    "Laatste update:",
    si_no_setups:             "Geen setups gevonden voor dit filter.",
    si_system_verdict:        "Systeem beoordeling",
    si_stats_header:          "Statistieken (alle marktomstandigheden)",
    si_hist_count:            "Aantal historisch (n)",
    si_win_rate_1h:           "Win-rate 1h",
    si_avg_pnl_1h_label:      "Gem. P&L 1h",
    si_avg_pnl_4h_label:      "Gem. P&L 4h",
    si_regime_analysis:       "BTC Regime Analyse",
    si_current_regime:        "Huidig regime",
    si_regime_unknown:        "onbekend regime",
    si_title_kans:            "Kans",
    si_title_beweging:        "Verwachte beweging",
    si_title_markt:           "Marktconditie",
    si_title_advies:          "Advies",
    si_bias_bullish:          " Recent momentum is positief (bullish).",
    si_bias_bearish:          " Recent momentum is negatief (bearish).",
    si_interp_win_in_regime:  " (win {win}% in dit regime)",
    si_interp_kans_hoog:      "Kans hoog: deze setup werkte historisch vaak goed ({win}% winrate). Van de {n} gevallen was ruim meer dan de helft winstgevend.",
    si_interp_kans_redelijk:  "Kans redelijk: de setup werkte iets vaker wel dan niet ({win}% winrate over {n} gevallen). Positief, maar niet uitzonderlijk sterk.",
    si_interp_kans_twijfel:   "Kans twijfelachtig: de setup had een winrate van {win}% over {n} gevallen. Minder dan de helft van de trades was winstgevend.",
    si_interp_kans_laag:      "Kans laag: slechts {win}% van de {n} historische gevallen was winstgevend. Deze setup verliest statistisch vaker dan hij wint.",
    si_interp_beweging_sterk: "Sterke opwaartse beweging: de prijs steeg gemiddeld +{pnl}% binnen 1 uur na dit signaal. Dat is een significante beweging.",
    si_interp_beweging_pos:   "Positieve beweging: de prijs steeg gemiddeld +{pnl}% binnen 1 uur. Klein maar consistent positief resultaat.",
    si_interp_beweging_neutraal: "Neutrale beweging: de prijs bewoog gemiddeld {pnl}% na 1 uur. Nauwelijks netto richting — wisselend resultaat.",
    si_interp_beweging_neg:   "Negatieve beweging: de prijs daalde gemiddeld {pnl}% na 1 uur. Dit signaal leidde historisch vaker tot verlies.",
    si_interp_regime_onbekend: "Het huidige marktregime is onbekend. Geen regime-analyse mogelijk.{bias}",
    si_interp_regime_gunstig: "Gunstig: de markt zit momenteel in een {regime}. Historisch presteert deze setup juist beter in dit regime.{bias}",
    si_interp_regime_ongunstig: "Ongunstig: de markt zit momenteel in een {regime}. Historisch presteert de setup slechter in dit regime.{bias}",
    si_interp_regime_weinig_data: "De markt zit in een {regime}, maar er zijn te weinig historische gevallen in dit regime (n={n}) voor een betrouwbare uitspraak.{bias}",
    si_interp_regime_vergelijkbaar: "De markt zit momenteel in een {regime}. De setup presteert vergelijkbaar onder beide marktomstandigheden{win}.{bias}",
    si_interp_advies_sterk:   "Het systeem beschouwt dit als een sterke kans (score {score}/100). Alle indicatoren wijzen in dezelfde richting: hoge winrate, positieve P&L en sterke statistische basis.",
    si_interp_advies_toestaan: "Het systeem staat dit signaal toe (score {score}/100). De statistieken zijn voldoende, maar er is geen uitzonderlijk sterke edge aanwezig.",
    si_interp_advies_zwak:    "Het systeem staat dit signaal zwak toe (score {score}/100). De edge is beperkt — gebruik dit signaal alleen met extra bevestiging.",
    si_interp_advies_skip:    "Het systeem slaat deze setup gewoonlijk over (score {score}/100). De statistieken rechtvaardigen geen positie: de kans op verlies is statistisch te groot.",
    si_interp_advies_onbekend: "Onvoldoende data om een betrouwbaar advies te geven (score {score}/100).",

    // --- STERK Quality page ---
    sq_title:           "STERK Advies Kwaliteit",
    sq_nav_bot:         "🤖 Bot Posities",
    sq_total_trades:    "Totaal STERK trades",
    sq_won_tp:          "Gewonnen (TP)",
    sq_lost_sl:         "Verloren (SL)",
    sq_avg_net_pnl:     "Gem. netto P&L",
    sq_total_fees:      "Totaal fees",
    sq_filter_tp:       "TP (gewonnen)",
    sq_filter_sl:       "SL (verloren)",
    sq_explanation:     "<b>Wat zie je hier?</b> Elke rij is een trade die de testbot heeft gedaan op basis van een <b>STERK</b> advies. Je kunt controleren of de STERK-adviezen ook echt goed afliepen. <b style='color:#3fb950'>TP</b> = doel bereikt (+4.5%), <b style='color:#f85149'>SL</b> = stop-loss geraakt (-2.0%), <b style='color:#d29922'>TIMEOUT</b> = na 2 uur automatisch gesloten. Netto P&L is na aftrek van <b>fees (0.2% round-trip)</b>.",
    sq_summary_header:  "Samenvatting in gewone taal",
    sq_cumul_chart:     "Cumulatief netto P&L (per afgesloten trade)",
    sq_per_day:         "Per dag",
    sq_dag_date:        "Datum",
    sq_dag_net:         "Netto",
    sq_no_closed:       "Nog geen gesloten trades.",
    sq_th_result:       "Resultaat",
    sq_th_close_price:  "Sluitprijs",
    sq_th_pnl_15m:      "P&L bij 15m",
    sq_th_pnl_1h:       "P&L bij 1u",
    sq_th_pnl_2h:       "P&L bij 2u",
    sq_th_pnl_total:    "P&L totaal",
    sq_no_trades_filter:"Geen trades gevonden voor dit filter.",
    sq_closed_trades:   "gesloten trades",
    sq_h_unit:          "u",
    sq_sum_closed:      "Van de <b>{n}</b> afgesloten trades was <b>{wins}</b> winstgevend ({wr}% winrate).",
    sq_sum_avg_dur:     "De gemiddelde looptijd was <b>{dur}</b>.",
    sq_sum_best_coin:   "Beste coin: <b style='color:#3fb950'>{coin}</b> (+${net} over {n} trade{s}).",
    sq_sum_worst_coin:  "Slechtste coin: <b style='color:#f85149'>{coin}</b> (-${net}).",
    sq_kpi_trades:      "Trades",
    sq_kpi_winrate:     "Winrate",
    sq_kpi_avg_net:     "Gem. netto/trade",
    sq_kpi_total_net:   "Totaal netto",

    // --- Chart page ---
    ch_timeframe:       "Tijdframe:",
    ch_pnl_after_1h:    "P&L na 1h",
    ch_pnl_after_4h:    "P&L na 4h",
    ch_rsi_at:          "RSI op moment",

    // --- Index dashboard ---
    ix_no_coins:          "Geen coins geladen...",
    ix_no_flash:          "Geen flash crashes (1u)",
    ix_flash_drop:        "daling",
    ix_flash_price:       "prijs",
    ix_agent_not_run:     "Nog niet gerund...",
    ix_decision:          "Beslissing:",
    ix_confidence:        "% vertrouwen",
    ix_strategy_lbl:      "Strategie:",
    ix_risk_lbl:          "Risk:",
    ix_waiting:           "wachten...",
    ix_no_perf:           "Nog geen signalen geëvalueerd. Komt vanzelf na 15 minuten...",
    ix_winrate_1h:        "Win-rate (1u)",
    ix_avg_pnl_1h:        "Gem. P&L (1u)",
    ix_evaluated:         "Geëvalueerd",
    ix_perf_15m:          "15m:",
    ix_perf_1h:           "1u:",
    ix_perf_4h:           "4u:",
    ix_balance_na:        "Balans niet beschikbaar.",
    ix_current_balance:   "💰 Huidige balans (Demo USDT)",
    ix_vs:                "t.o.v.",
    ix_orders:            "Orders",
    ix_peak_balance:      "Piek balans",
    ix_avg_pnl_1h_label:  "Gem. P&L na 1u",
    ix_signals_evaluated: "Signalen geëvalueerd",
    ix_volume_traded:     "Volume verhandeld",
    ix_recent_orders:     "Recente orders:",
    ix_render_error:      "⚠️ Weergavefout:",
    ix_hist_max:          "MAX (alle beschikbare data)",
    ix_hist_max_full:     "MAX (volledige geschiedenis)",
    ix_hist_months:       "{n} maanden",
    ix_analyzing:         "{sym} analyseren: {period} × 1h candles... even geduld (~15-60s voor MAX).",
    ix_result_1h:         "Resultaat na 1 uur:",
    ix_signals:           "Signalen",
    ix_per_signal_type:   "Per signaaltype:",
    ix_backtest_disc:     "⚠️ Backtest = historische simulatie. Geen garantie voor toekomstige resultaten.",
    ix_filtered_on:       "gefilterd op",
    ix_live_prefix:       "⚡ Live:",
    ix_iron_law:          "⚠️ IJZEREN WET ACTIEF — Pre-crash score {score}/100. Kooporders geblokkeerd.",
    ix_h_balance:         "💰 Demo Account — BloFin Paper Trading",
    ix_h_coins:           "📊 Coin Overzicht",
    ix_h_exchange:        "🏦 Exchange Vergelijking — Live Prijs per Exchange",
    ix_h_system:          "⚙️ Systeem",
    ix_h_flash:           "⚡ Flash Crash Detector",
    ix_h_agent:           "🤖 AI Agent Workflow (Research → Strategy → Risk → Verify)",
    ix_h_perf:            "📈 Signaal Performance — Wat hadden eerdere signalen opgeleverd?",
    ix_h_hist:            "🔬 Historische Backtest — alle coins, alle tijden",
    ix_mode:              "Mode",
    ix_coins_followed:    "Coins gevolgd",
    ix_flash_crashes:     "Flash crashes (1u)",
    ix_max_crash_score:   "Max crash score",
    ix_error_reconnect:   "⚠️ Fout ({msg}). Herverbinden...",
    ix_api_unreachable:   "⚠️ Kan Control API niet bereiken ({msg}).",
    ix_loading_prices:    "Laden prijzen...",
    ix_offline:           "— offline —",
    ix_exch_desc:         "{base}/USDT — gewogen consensus (Coinbase 35% gewicht) — BloFin is jouw handelsplatform",
    ix_exch_price:        "Prijs",
    ix_exch_vs_consensus: "vs Consensus",
    ix_exch_weighted:     "Gewogen consensus:",
    ix_exch_online:       "{n}/6 online",
    ix_hist_followed:     "── Gevolgd door Kimi ──",
    ix_or:                "of",
    ix_period:            "Periode:",
    ix_start_backtest:    "▶ Start Backtest",
    ix_signal_filter:     "Signaal filter:",
    ix_all:               "Alle",
    ix_nav_quality:       "📉 Kwaliteit",
  },

  en: {
    // --- Page titles ---
    title_live_signals:       "Live Signals",
    title_setup_intelligence: "Setup Intelligence",
    title_bot_positions:      "Bot Positions",
    title_sterk_quality:      "STERK Quality",
    title_chart:              "Chart",

    // --- Navigation ---
    nav_live:       "⚡ Live",
    nav_setup:      "📊 Setup Intel",
    nav_chart:      "📈 Chart",
    nav_positions:  "🤖 Bot",
    nav_quality:    "📉 STERK",
    nav_logout:     "Log out",
    nav_back:       "← Back",
    nav_dashboard:  "Dashboard",
    nav_setup_intel:"← Setup Intel",

    // --- Status bar ---
    btc_regime:         "BTC Regime",
    active_signals:     "Active signals",
    sterk_active:       "STERK active",
    coins_monitored:    "Coins monitored",
    bot_status:         "Bot status",
    open_slots:         "Open slots",
    updated:            "Updated",
    connected:          "Connected",

    // --- Filters ---
    filter_label:       "Filter:",
    filter_all:         "All coins",
    filter_signal:      "With signal",
    filter_sterk:       "STERK + TOESTAAN",
    refresh:            "Refresh now",
    auto_refresh:       "Auto-refresh in",
    auto_refresh_unit:  "s",

    // --- Table headers ---
    col_coin:           "Coin",
    col_price:          "Live price",
    col_rsi:            "RSI (1h)",
    col_macd:           "MACD",
    col_adx:            "ADX",
    col_ema:            "EMA regime",
    col_signal:         "Signal now",
    col_verdict:        "Verdict",
    col_score:          "Score",
    col_win_pct:        "Win%",
    col_avg_pnl:        "Avg +1h",
    col_data_from:      "Data from",
    col_last_signal:    "Last signal",
    col_entry:          "Entry price",
    col_exit:           "Exit price",
    col_stake:          "Stake",
    col_duration:       "Duration",
    col_gross_pnl:      "Gross P&L",
    col_net_pnl:        "Net P&L",
    col_fee:            "Fee",
    col_reason:         "Reason",
    col_trades:         "Trades",
    col_winrate:        "Win rate",
    col_win_hist:       "Win% historical",
    col_avg_hist:       "Avg PnL hist.",
    col_net_trade:      "Avg net/trade",
    col_total_net:      "Total net",
    col_chance:         "Probability",
    col_expected:       "Expected move",
    col_market:         "Market condition",
    col_status:         "Status",
    col_setup_score:    "Setup score",
    col_n_hist:         "Historical (n)",

    // --- Signals ---
    no_signal:          "No signal",
    signal_active:      "Active now",
    time_recent:        "recent",
    time_h_old:         "h ago",
    time_d_old:         "d ago",
    hours_ago:          "h ago",
    days_ago:           "d ago",
    last_signal_tooltip: "How long ago this signal was last active",

    // --- MACD labels ---
    macd_neutral:       "neutral",

    // --- Verdicts ---
    verdict_sterk:        "STERK",
    verdict_toestaan:     "TOESTAAN",
    verdict_toestaan_zwak: "TOESTAAN_ZWAK",
    verdict_skip:         "SKIP",

    // --- Bot controls ---
    bot_start:          "Start bot",
    bot_stop:           "Stop bot",
    bot_running:        "Bot running — waiting for a STERK signal.",
    bot_start_prompt:   "Start the bot using the button in the top right.",
    test_trade:         "Test trade",

    // --- Chart ---
    chart_error:        "Chart error:",
    chart_hover:        "Hover over chart for OHLCV values...",
    show_setup_markers: "Show Setup Intel STERK/TOESTAAN moments",
    show_bot_trades:    "Show testbot trades",
    coin_placeholder:   "Search coin...",
    coin_hint:          "Select a coin from the dropdown or enter a symbol.",
    coin_fill:          "Please enter a symbol.",
    open_chart:         "Open chart",

    // --- Loading / errors ---
    loading:            "Loading...",
    loading_price:      "loading...",
    error:              "Error",
    error_bot_toggle:   "Error toggling bot: ",
    error_loading:      "Error loading:",
    no_signals_filter:  "No signals found for this filter.",
    no_data_winrate:    "No historical win rate data available for this setup.",
    no_data_pnl:        "No average P&L data available for this setup.",

    // --- Detail panel: live signals ---
    dp_indicators_from:   "Indicators from:",
    dp_current_indicators:"Current indicators (1h)",
    dp_live_price:        "Live price",
    dp_macd_hist:         "MACD histogram",
    dp_bb_position:       "BB position",
    dp_volume_ratio:      "Volume ratio",
    dp_volume_avg:        "× avg.",
    dp_historical:        "Historical quality",
    dp_no_signal:         "no signal",
    dp_win_pct_1h:        "Win% (1h)",
    dp_avg_pnl_1h:        "Avg P&L (1h)",
    dp_n_trades:          "Number of trades (n)",
    dp_edge_strength:     "Edge strength",
    dp_regime_fit:        "Regime fit",

    // --- Interpretation texts ---
    interp_signal:        "Signal:",
    interp_hist_intro:    "Historically this signal on",
    interp_win_chance:    "win probability",
    interp_with_avg:      "with average",
    interp_after_1h:      "after 1 hour",
    interp_based_on:      "based on",
    interp_hist_trades:   "historical trades",
    interp_sterk:         "Strong setup — this is one of the best setups in the system.",
    interp_toestaan:      "Allowed — solid setup, the bot may act on this.",
    interp_zwak:          "Weak — marginal setup, bot does not trade this.",
    interp_skip:          "Skip — negative expectation, bot skips this.",
    interp_no_signal:     "No active signal at this time.",
    interp_bot_monitors:  "The bot is monitoring this coin but taking no action right now.",

    // --- STERK Quality summaries ---
    summary_good:       "STERK signals are performing well. More than 60% of trades were profitable and the total result is positive.",
    summary_ok:         "STERK signals are performing reasonably. Win rate is acceptable and the result is positive.",
    summary_mixed:      "Mixed picture: win rate is reasonable but fees and losing trades are weighing on the result. More data needed.",
    summary_early:      "STERK signals are not yet performing as expected. Collect more data for a reliable picture.",

    // --- Misc ---
    download_csv:       "Download as CSV",
    custom_symbol:      "Custom symbol, e.g. APEUSDT",
    regime_bull:        "rising market (BULL)",
    regime_bear:        "falling market (BEAR)",
    close:              "Close",

    // --- Setup Intelligence page ---
    si_sort_label:            "Sort:",
    si_sort_avg_pnl:          "Avg. P&L 1h",
    si_sort_count:            "Count (n)",
    si_th_signal:             "Signal",
    si_last_update_prefix:    "Last update:",
    si_no_setups:             "No setups found for this filter.",
    si_system_verdict:        "System assessment",
    si_stats_header:          "Statistics (all market conditions)",
    si_hist_count:            "Historical count (n)",
    si_win_rate_1h:           "Win rate 1h",
    si_avg_pnl_1h_label:      "Avg. P&L 1h",
    si_avg_pnl_4h_label:      "Avg. P&L 4h",
    si_regime_analysis:       "BTC Regime Analysis",
    si_current_regime:        "Current regime",
    si_regime_unknown:        "unknown regime",
    si_title_kans:            "Probability",
    si_title_beweging:        "Expected movement",
    si_title_markt:           "Market condition",
    si_title_advies:          "Advice",
    si_bias_bullish:          " Recent momentum is positive (bullish).",
    si_bias_bearish:          " Recent momentum is negative (bearish).",
    si_interp_win_in_regime:  " (win {win}% in this regime)",
    si_interp_kans_hoog:      "High probability: this setup historically performed well ({win}% win rate). More than half of {n} cases were profitable.",
    si_interp_kans_redelijk:  "Fair probability: the setup worked slightly more often than not ({win}% win rate over {n} cases). Positive, but not exceptionally strong.",
    si_interp_kans_twijfel:   "Doubtful probability: the setup had a win rate of {win}% over {n} cases. Less than half of trades were profitable.",
    si_interp_kans_laag:      "Low probability: only {win}% of {n} historical cases were profitable. This setup statistically loses more than it wins.",
    si_interp_beweging_sterk: "Strong upward movement: price rose on average +{pnl}% within 1 hour after this signal. That is a significant move.",
    si_interp_beweging_pos:   "Positive movement: price rose on average +{pnl}% within 1 hour. Small but consistently positive result.",
    si_interp_beweging_neutraal: "Neutral movement: price moved on average {pnl}% after 1 hour. Barely any net direction — mixed results.",
    si_interp_beweging_neg:   "Negative movement: price declined on average {pnl}% after 1 hour. This signal historically led to loss more often.",
    si_interp_regime_onbekend: "The current market regime is unknown. No regime analysis possible.{bias}",
    si_interp_regime_gunstig: "Favorable: the market is currently in a {regime}. Historically this setup performs better in this regime.{bias}",
    si_interp_regime_ongunstig: "Unfavorable: the market is currently in a {regime}. Historically the setup performs worse in this regime.{bias}",
    si_interp_regime_weinig_data: "The market is in a {regime}, but there are too few historical cases in this regime (n={n}) for a reliable conclusion.{bias}",
    si_interp_regime_vergelijkbaar: "The market is currently in a {regime}. The setup performs similarly under both market conditions{win}.{bias}",
    si_interp_advies_sterk:   "The system considers this a strong opportunity (score {score}/100). All indicators point in the same direction: high win rate, positive P&L, and strong statistical base.",
    si_interp_advies_toestaan: "The system allows this signal (score {score}/100). The statistics are sufficient, but no exceptionally strong edge is present.",
    si_interp_advies_zwak:    "The system weakly allows this signal (score {score}/100). The edge is limited — only use this signal with extra confirmation.",
    si_interp_advies_skip:    "The system typically skips this setup (score {score}/100). The statistics do not justify a position: the probability of loss is statistically too high.",
    si_interp_advies_onbekend: "Insufficient data to provide a reliable recommendation (score {score}/100).",

    // --- STERK Quality page ---
    sq_title:           "STERK Signal Quality",
    sq_nav_bot:         "🤖 Bot Positions",
    sq_total_trades:    "Total STERK trades",
    sq_won_tp:          "Won (TP)",
    sq_lost_sl:         "Lost (SL)",
    sq_avg_net_pnl:     "Avg. net P&L",
    sq_total_fees:      "Total fees",
    sq_filter_tp:       "TP (won)",
    sq_filter_sl:       "SL (lost)",
    sq_explanation:     "<b>What do you see here?</b> Each row is a trade made by the testbot based on a <b>STERK</b> signal. You can verify whether the STERK signals actually performed well. <b style='color:#3fb950'>TP</b> = target reached (+4.5%), <b style='color:#f85149'>SL</b> = stop-loss hit (-2.0%), <b style='color:#d29922'>TIMEOUT</b> = automatically closed after 2 hours. Net P&L is after deducting <b>fees (0.2% round-trip)</b>.",
    sq_summary_header:  "Summary in plain language",
    sq_cumul_chart:     "Cumulative net P&L (per closed trade)",
    sq_per_day:         "Per day",
    sq_dag_date:        "Date",
    sq_dag_net:         "Net",
    sq_no_closed:       "No closed trades yet.",
    sq_th_result:       "Result",
    sq_th_close_price:  "Close price",
    sq_th_pnl_15m:      "P&L at 15m",
    sq_th_pnl_1h:       "P&L at 1h",
    sq_th_pnl_2h:       "P&L at 2h",
    sq_th_pnl_total:    "Total P&L",
    sq_no_trades_filter:"No trades found for this filter.",
    sq_closed_trades:   "closed trades",
    sq_h_unit:          "h",
    sq_sum_closed:      "Of the <b>{n}</b> closed trades, <b>{wins}</b> were profitable ({wr}% win rate).",
    sq_sum_avg_dur:     "The average duration was <b>{dur}</b>.",
    sq_sum_best_coin:   "Best coin: <b style='color:#3fb950'>{coin}</b> (+${net} over {n} trade{s}).",
    sq_sum_worst_coin:  "Worst coin: <b style='color:#f85149'>{coin}</b> (-${net}).",
    sq_kpi_trades:      "Trades",
    sq_kpi_winrate:     "Win rate",
    sq_kpi_avg_net:     "Avg. net/trade",
    sq_kpi_total_net:   "Total net",

    // --- Chart page ---
    ch_timeframe:       "Timeframe:",
    ch_pnl_after_1h:    "P&L after 1h",
    ch_pnl_after_4h:    "P&L after 4h",
    ch_rsi_at:          "RSI at moment",

    // --- Index dashboard ---
    ix_no_coins:          "No coins loaded...",
    ix_no_flash:          "No flash crashes (1h)",
    ix_flash_drop:        "drop",
    ix_flash_price:       "price",
    ix_agent_not_run:     "Not run yet...",
    ix_decision:          "Decision:",
    ix_confidence:        "% confidence",
    ix_strategy_lbl:      "Strategy:",
    ix_risk_lbl:          "Risk:",
    ix_waiting:           "waiting...",
    ix_no_perf:           "No signals evaluated yet. Will appear automatically after 15 minutes...",
    ix_winrate_1h:        "Win rate (1h)",
    ix_avg_pnl_1h:        "Avg P&L (1h)",
    ix_evaluated:         "Evaluated",
    ix_perf_15m:          "15m:",
    ix_perf_1h:           "1h:",
    ix_perf_4h:           "4h:",
    ix_balance_na:        "Balance not available.",
    ix_current_balance:   "💰 Current balance (Demo USDT)",
    ix_vs:                "vs",
    ix_orders:            "Orders",
    ix_peak_balance:      "Peak balance",
    ix_avg_pnl_1h_label:  "Avg P&L after 1h",
    ix_signals_evaluated: "Signals evaluated",
    ix_volume_traded:     "Volume traded",
    ix_recent_orders:     "Recent orders:",
    ix_render_error:      "⚠️ Render error:",
    ix_hist_max:          "MAX (all available data)",
    ix_hist_max_full:     "MAX (full history)",
    ix_hist_months:       "{n} months",
    ix_analyzing:         "Analyzing {sym}: {period} × 1h candles... please wait (~15-60s for MAX).",
    ix_result_1h:         "Result after 1 hour:",
    ix_signals:           "Signals",
    ix_per_signal_type:   "Per signal type:",
    ix_backtest_disc:     "⚠️ Backtest = historical simulation. No guarantee for future results.",
    ix_filtered_on:       "filtered on",
    ix_live_prefix:       "⚡ Live:",
    ix_iron_law:          "⚠️ IRON LAW ACTIVE — Pre-crash score {score}/100. Buy orders blocked.",
    ix_h_balance:         "💰 Demo Account — BloFin Paper Trading",
    ix_h_coins:           "📊 Coin Overview",
    ix_h_exchange:        "🏦 Exchange Comparison — Live Price per Exchange",
    ix_h_system:          "⚙️ System",
    ix_h_flash:           "⚡ Flash Crash Detector",
    ix_h_agent:           "🤖 AI Agent Workflow (Research → Strategy → Risk → Verify)",
    ix_h_perf:            "📈 Signal Performance — What would earlier signals have returned?",
    ix_h_hist:            "🔬 Historical Backtest — all coins, all time",
    ix_mode:              "Mode",
    ix_coins_followed:    "Coins tracked",
    ix_flash_crashes:     "Flash crashes (1h)",
    ix_max_crash_score:   "Max crash score",
    ix_error_reconnect:   "⚠️ Error ({msg}). Reconnecting...",
    ix_api_unreachable:   "⚠️ Cannot reach Control API ({msg}).",
    ix_loading_prices:    "Loading prices...",
    ix_offline:           "— offline —",
    ix_exch_desc:         "{base}/USDT — weighted consensus (Coinbase 35% weight) — BloFin is your exchange",
    ix_exch_price:        "Price",
    ix_exch_vs_consensus: "vs Consensus",
    ix_exch_weighted:     "Weighted consensus:",
    ix_exch_online:       "{n}/6 online",
    ix_hist_followed:     "── Tracked by Kimi ──",
    ix_or:                "or",
    ix_period:            "Period:",
    ix_start_backtest:    "▶ Start Backtest",
    ix_signal_filter:     "Signal filter:",
    ix_all:               "All",
    ix_nav_quality:       "📉 STERK",
  }

};

/**
 * Get translated string for the current language.
 * Falls back to Dutch if translation is missing.
 */
function t(key) {
  return (TRANSLATIONS[LANG] || TRANSLATIONS["nl"])[key] || TRANSLATIONS["nl"][key] || key;
}

/**
 * Switch language and reload the page (all content re-renders on load).
 */
function setLang(lang) {
  localStorage.setItem("oc_lang", lang);
  location.reload();
}

/**
 * Highlight the active language button. Call this from each page's initI18n().
 */
function initLangButtons() {
  document.querySelectorAll(".lang-btn[data-lang]").forEach(function(b) {
    b.classList.toggle("lang-active", b.dataset.lang === LANG);
  });
}

// Auto-inject CSS for the NL/EN toggle so each page doesn't need to copy it
(function() {
  var s = document.createElement("style");
  s.textContent = ".lang-toggle{display:inline-flex;gap:2px;margin-left:6px}" +
    ".lang-btn{font-size:.7rem;padding:3px 7px;border-radius:4px;border:1px solid #30363d;" +
    "background:#21262d;color:#8b949e;cursor:pointer}" +
    ".lang-btn:hover{background:#2d333b;color:#c9d1d9}" +
    ".lang-btn.lang-active{background:#1f4068;color:#58a6ff;border-color:#1158a7;font-weight:700}";
  document.head.appendChild(s);
})();
