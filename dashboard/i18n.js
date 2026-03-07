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

const LANG = "nl"; // Change to "en" for English, "de" for German, etc.

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

    // --- Status bar ---
    btc_regime:         "BTC Regime",
    active_signals:     "Actieve signalen",
    sterk_active:       "STERK actief",
    bot_status:         "Bot status",
    open_slots:         "Open slots",
    updated:            "Bijgewerkt",
    connected:          "Verbonden",

    // --- Filters ---
    filter_all:         "Alle coins",
    filter_signal:      "Met signaal",
    filter_sterk:       "Alleen STERK+TOESTAAN",
    refresh:            "Ververs",

    // --- Table headers ---
    col_coin:           "Coin",
    col_price:          "Prijs",
    col_rsi:            "RSI",
    col_macd:           "MACD",
    col_adx:            "ADX",
    col_ema:            "EMA regime",
    col_signal:         "Actief signaal",
    col_verdict:        "Advies",
    col_score:          "Setup score",
    col_win_pct:        "Win%",
    col_avg_pnl:        "Gem. P&L 1h",
    col_n:              "Historisch (n)",
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

    // --- Signals ---
    no_signal:          "Geen signaal",
    signal_active:      "Nu actief",
    hours_ago:          "h geleden",
    days_ago:           "d geleden",
    last_signal_tooltip: "Hoe lang geleden het signaal voor het laatste actief was",

    // --- Verdicts (keep as-is or translate) ---
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
    open_chart:         "Open chart",

    // --- Loading / errors ---
    loading:            "Laden...",
    error:              "Fout",
    error_bot_toggle:   "Fout bij bot toggle: ",
    no_data_winrate:    "Geen historische winrate-data beschikbaar voor deze setup.",
    no_data_pnl:        "Geen gemiddelde P&L data beschikbaar voor deze setup.",

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

    // --- Status bar ---
    btc_regime:         "BTC Regime",
    active_signals:     "Active signals",
    sterk_active:       "STERK active",
    bot_status:         "Bot status",
    open_slots:         "Open slots",
    updated:            "Updated",
    connected:          "Connected",

    // --- Filters ---
    filter_all:         "All coins",
    filter_signal:      "With signal",
    filter_sterk:       "STERK+TOESTAAN only",
    refresh:            "Refresh",

    // --- Table headers ---
    col_coin:           "Coin",
    col_price:          "Price",
    col_rsi:            "RSI",
    col_macd:           "MACD",
    col_adx:            "ADX",
    col_ema:            "EMA regime",
    col_signal:         "Active signal",
    col_verdict:        "Advice",
    col_score:          "Setup score",
    col_win_pct:        "Win%",
    col_avg_pnl:        "Avg PnL 1h",
    col_n:              "Historical (n)",
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

    // --- Signals ---
    no_signal:          "No signal",
    signal_active:      "Active now",
    hours_ago:          "h ago",
    days_ago:           "d ago",
    last_signal_tooltip: "How long ago this signal was last active",

    // --- Verdicts (keep Dutch names as brand terms) ---
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
    error:              "Error",
    error_bot_toggle:   "Error toggling bot: ",
    no_data_winrate:    "No historical win rate data available for this setup.",
    no_data_pnl:        "No average P&L data available for this setup.",

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
  }

};

/**
 * Get translated string for the current language.
 * Falls back to the key name if translation is missing.
 */
function t(key) {
  return (TRANSLATIONS[LANG] || TRANSLATIONS["nl"])[key] || key;
}
