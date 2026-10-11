// Generated from the audited source. Edit the extractor/ports, never algorithms.
export function createCore(ports) {
  const Date=ports.Date || globalThis.Date;
  const Math=ports.Math || globalThis.Math;
  const crypto=ports.crypto || globalThis.crypto;
  const localStorage=ports.storage;
  const navigator=ports.navigator;
  const tracker=ports.tracker;
  const state=ports.state;
  const runtimeState=ports.runtimeState;
  const runtimeCache=ports.runtimeCache;
  const runtimeMonitor=ports.runtimeMonitor;
  const eventEngine=ports.eventEngine;
    const STORAGE_KEY = 'sina_stock_range_history_v1';
    const DAILY_RANGE_KEY = 'a_stock_daily_range_v12';
    const PROFILE_KEY = 'sina_stock_profile_cache_v1';
    const BOARD_PROFILE_KEY = 'eastmoney_stock_board_profiles_v1';
    const TRACKER_KEY = 'sina_stock_auto_tracker_v1';
    const DAILY_RUNTIME_DATE_KEY = 'a_stock_v2a_runtime_date_v121';
    const CSV_HANDLE_DB = 'a_stock_tracker_csv_handles_v1';
    const CSV_HANDLE_STORE = 'handles';
    const EASTMONEY_HOSTS = [
      'https://push2.eastmoney.com',
      'https://82.push2.eastmoney.com',
      'https://push2his.eastmoney.com',
      'https://push2delay.eastmoney.com'
    ];
    const EASTMONEY_TOKEN = 'fa5fd1943c7b386f172d6893dbfba10b';
    const MAX_HISTORY = 30;
    const MAX_TRACK_STOCKS = 5;
    const MAX_DAILY_RANGE_STOCKS = 5;
    const RUNTIME_SAMPLE_INTERVAL_MS = 5000;
    const RUNTIME_WINDOW_TOLERANCE_MS = 7500;
    const RUNTIME_SAMPLE_INTERVAL_SECONDS = RUNTIME_SAMPLE_INTERVAL_MS / 1000;
    const RUNTIME_BUFFER_WINDOW_SECONDS = 120;
    const RUNTIME_BUFFER_MAX = Math.floor(RUNTIME_BUFFER_WINDOW_SECONDS / RUNTIME_SAMPLE_INTERVAL_SECONDS);
    const RUNTIME_ARCHIVE_INTERVAL_MS = 30000;
    const RUNTIME_STATE_WRITE_INTERVAL_MS = 10000;
    const RUNTIME_CACHE_TTL = {
      stock: 5000,
      industry: 15000,
      indexes: 15000,
      breadth: 60000,
      daily: 24 * 60 * 60 * 1000
    };
    const RUNTIME_DIRECTORY_HANDLE_KEY = '__runtime_v1_output_directory__';
    const MARKET_RAW_FILE_NAME = 'market_raw.csv';
    const RUNTIME_STATE_FILE_NAME = 'runtime_state.json';
    const EVENTS_FILE_NAME = 'events.jsonl';
    const ANALYSIS_STATE_FILE_NAME = 'analysis_state.json';
    const DECISION_CHECKPOINT_FILE_NAME = 'decision_checkpoint.json';
    const AI_HANDOFF_FILE_NAME = 'ai_handoff.json';
    const EVENT_ENGINE_STORAGE_KEY = 'a_stock_v2a_event_engine_v1';
    const EVENT_SCAN_INTERVAL_MS = 1000;
    const EVENT_RECENT_CONTEXT_MINUTES = 20;
    const EVENT_RECENT_CONTEXT_ROWS = 5;
    const MAX_HANDOFF_HISTORY = 5;
    const TRACKING_STATUS = Object.freeze({ ACTIVE: 'ACTIVE', PAUSED: 'PAUSED', DROPPED: 'DROPPED' });
    const TRACK_TIMES = buildFiveMinuteTrackTimes();
    const INDEXES = [
      { key: 'shanghai', label: '上证', symbol: 'sh000001' },
      { key: 'chinext', label: '创业', symbol: 'sz399006' },
      { key: 'beijing', label: '北交', symbol: 'bj899050' },
      { key: 'star', label: '科创', symbol: 'sh000680' }
    ];
    const TRACKER_CSV_HEADERS = [
      '股票名称','股票代码','tracking_session_id','所属行业层级','跟踪板块','板块代码','输出时点','统计区间',
      '区间开盘','区间最高','区间最低','当前价',
      '累计成交量(股)','Δ成交量(股)','累计成交额-原始(元)','成交额状态','Δ成交额(元)','累计换手(%)','Δ换手(pp)',
      '累计VWAP','区间VWAP','个股涨跌(%)','行业涨跌(%)', ...INDEXES.map(index => `${index.label}(%)`),
      '同时段量比','量比样本数','现价-VWAP(%)','区间涨跌(%)','价格推动效率(%/1pp换手)',
      '个股-行业Alpha(pp)','行业宽度-成分股中位数涨跌(%)','行业有效成分数','事件标签',
      'VWAP成交数据源','行业宽度数据源','行业宽度状态','股票行情最后时点','实际查询时间'
    ];
    const MARKET_RAW_HEADERS = [
      'timestamp','symbol','name','data_status','price','open','high','low',
      'cumulative_volume','delta_volume_30s','cumulative_amount','delta_amount_30s',
      'cumulative_turnover','delta_turnover_30s','trade_source','trade_source_captured_at','trade_data_age_ms',
      'vwap','price_vwap_pct',
      'stock_pct','industry_pct','alpha','alpha_change_30s','alpha_change_60s',
      'industry_breadth','sh_pct','cyb_pct','bse_pct','star_pct'
    ];
    const DAILY_RANGE_HEADERS = [
      '输出时点','统计区间','区间开盘','区间最高','区间最低','当前价',
      '累计成交量','Δ成交量','累计成交额（原始）','成交额状态','Δ成交额','累计换手','Δ换手',
      '累计VWAP','区间VWAP','个股涨跌','行业涨跌', ...INDEXES.map(index => index.label),
      '同时段量比','现价-VWAP%','区间涨跌','价格推动效率','个股-行业Alpha','行业宽度(成分股中位数)','事件标签'
    ];
    const EVENT_DEFINITIONS = Object.freeze({
      '缩量回踩': { type: 'LOW_VOLUME_PULLBACK', severity: 'INFO' },
      '新高': { type: 'NEW_HIGH', severity: 'WATCH' },
      '新低': { type: 'NEW_LOW', severity: 'WATCH' },
      'VWAP重新夺回': { type: 'VWAP_RECLAIM', severity: 'WATCH' },
      '支撑二次测试': { type: 'SUPPORT_RETEST', severity: 'WATCH' },
      '价格效率衰减': { type: 'PRICE_EFFICIENCY_DECAY', severity: 'WATCH' },
      '放量破位': { type: 'VOLUME_BREAKDOWN', severity: 'IMPORTANT' },
      'Alpha快速恶化': { type: 'ALPHA_DETERIORATE', severity: 'IMPORTANT' }
    });
    const EVENT_SEVERITY_ORDER = Object.freeze({ INFO: 1, WATCH: 2, IMPORTANT: 3, CRITICAL: 4 });

    let jsonpCounter=0;

  const clearPendingAckUi=ports.clearPendingAckUi;
  const deleteCsvHandle=ports.deleteCsvHandle;
  const loadJsonpCallback=ports.loadJsonpCallback;
  const loadJsonpVariable=ports.loadJsonpVariable;
  const renderEventCenter=ports.renderEventCenter;
  const renderRealtimeMonitor=ports.renderRealtimeMonitor;
  const renderTracker=ports.renderTracker;
  const saveBoardProfiles=ports.saveBoardProfiles;
  const saveEventEngineStore=ports.saveEventEngineStore;
  const saveProfiles=ports.saveProfiles;
  const saveTrackerStore=ports.saveTrackerStore;
  const showToast=ports.showToast;

    function assignTrackingSessionToItem(item, symbol, now = new Date()) {
      const date = chinaToday();
      const previous = trackingSessionsForSymbol(symbol, date).slice(-1)[0] || null;
      tracker.store.session_seq_by_symbol = tracker.store.session_seq_by_symbol || {};
      const trackingSessionId = nextTrackingSessionId(
        symbol, date, tracker.store.sessions, tracker.store.session_seq_by_symbol
      );
      const start = trackerSessionStartMetadata(now);
      item.tracking_session_id = trackingSessionId;
      item.previous_tracking_session_id = previous ? previous.tracking_session_id : null;
      item.tracking_started_at = start.started_at;
      item.tracking_start_requested_time = start.start_requested_time;
      item.lifecycle_status = TRACKING_STATUS.ACTIVE;
      item.aiSelected = true;
      return trackingSessionId;
    }

    function backfillTrackerBoardChanges(session, dataset, replaceAll = false) {
      if (!dataset.board || !dataset.boardMinuteData || !dataset.boardDailyBars) return 0;
      let updated = 0;
      session.rows.forEach(row => {
        if (!replaceAll && row.boardCode === dataset.board.code && hasNumber(row.boardChange)) return;
        const value = boardChangeAt(
          dataset.boardMinuteData, dataset.boardDailyBars, session.date,
          row.requestedTime || row.intervalEnd || '15:00'
        );
        row.boardCode = dataset.board.code;
        row.boardName = dataset.board.name;
        row.boardChange = value;
        row.alpha = hasNumber(row.stockChange) && hasNumber(value) ? row.stockChange - value : null;
        if (replaceAll && row.boardMedianCode && row.boardMedianCode !== dataset.board.code) {
          row.boardMedianChange = null;
          row.boardMedianTotal = null;
          row.boardMedianTotal = null;
          row.boardMedianCode = '';
          row.boardMedianMethod = '';
          row.boardMedianCapturedAt = '';
          row.boardMedianStatus = canRetryBreadthRow({ ...row, boardCode: dataset.board.code }) ? 'pending' : 'historical';
          row.boardMedianPending = row.boardMedianStatus === 'pending';
          row.boardMedianError = '';
        }
        row.boardPending = !hasNumber(value);
        if (hasNumber(value)) updated += 1;
      });
      return updated;
    }

    function backfillTrackerMetrics(session, dataset) {
      let updated = 0;
      session.rows.sort((a, b) => String(a.requestedTime).localeCompare(String(b.requestedTime)) || String(a.capturedAt).localeCompare(String(b.capturedAt)));
      session.rows.forEach((row, index) => {
        const before = JSON.stringify([
          row.intervalStart, row.open, row.high, row.low, row.cumulativeVolume,
          row.turnover, row.amount, row.vwap, row.vwapGap, row.volumeRatio, row.alpha,
          row.volumeSource, row.vwapIssue
        ]);
        if (row.requestedTime === '09:25') {
          row.auctionPoint = true;
          row.open = hasNumber(row.open) ? row.open : row.price;
          row.high = hasNumber(row.high) ? row.high : row.price;
          row.low = hasNumber(row.low) ? row.low : row.price;
          row.intervalStart = '09:15';
          row.intervalEnd = '09:25';
          row.alpha = hasNumber(row.stockChange) && hasNumber(row.boardChange)
            ? row.stockChange - row.boardChange : null;
        } else {
          const previous = trackerComparisonPrevious(session.rows, row.requestedTime, index);
          const start = trackerIntervalStart(previous, row.requestedTime);
          const end = row.requestedTime || row.intervalEnd || '15:00';
          row.intervalStart = start;
          row.intervalEnd = end;
          let intervalRows = barsInTradingInterval(dataset.stockBars, session.date, start, end);
          if (row.openingPoint || end === '09:30') {
            row.open = row.price;
            row.high = row.price;
            row.low = row.price;
          } else if (intervalRows.length) {
            row.open = intervalRows[0].open;
            row.high = maxOf(intervalRows, 'high');
            row.low = minOf(intervalRows, 'low');
          }
          const cumulativeRows = dataset.stockBars.filter(bar =>
            bar.date === session.date && bar.time.slice(0, 5) >= '09:30' && bar.time.slice(0, 5) <= end
          );
          let refreshedMetrics = null;
          const hasRealAuctionMetrics = end === '09:30' && previous && previous.requestedTime === '09:25'
            && !previous.auctionEstimated && hasNumber(previous.cumulativeVolume) && hasNumber(previous.amount);
          if (end !== '09:30' || !hasRealAuctionMetrics) {
            refreshedMetrics = cumulativeTradeMetricsForTime(
              dataset, session.date, end, row.source || 'auto', cumulativeRows
            );
            row.cumulativeVolume = refreshedMetrics && hasNumber(refreshedMetrics.volume) ? refreshedMetrics.volume : null;
            row.turnover = hasNumber(row.cumulativeVolume) ? row.cumulativeVolume / dataset.profile.floatShares * 100 : null;
            row.amount = refreshedMetrics && hasNumber(refreshedMetrics.amount) ? refreshedMetrics.amount : null;
            row.amountTrusted = refreshedMetrics ? refreshedMetrics.amountTrusted !== false : false;
            row.volumeSource = refreshedMetrics ? refreshedMetrics.source : '';
            row.vwapIssue = refreshedMetrics && refreshedMetrics.issue
              ? refreshedMetrics.issue
              : refreshedMetrics ? '' : '成交额/成交量暂不可用，VWAP无法计算';
            row.vwapLow = refreshedMetrics ? refreshedMetrics.low : null;
            row.vwapHigh = refreshedMetrics ? refreshedMetrics.high : null;
          } else if (!row.volumeSource || !hasNumber(row.cumulativeVolume) || !hasNumber(row.amount)) {
            row.cumulativeVolume = null;
            row.turnover = null;
            row.amount = null;
            row.amountTrusted = false;
            row.volumeSource = '';
            row.vwapIssue = '';
            row.vwapLow = null;
            row.vwapHigh = null;
          }
          row.vwap = refreshedMetrics && hasNumber(refreshedMetrics.vwap) ? refreshedMetrics.vwap
            : end === '09:30' && hasNumber(row.amount) && Number(row.amount) > 0
              && hasNumber(row.cumulativeVolume) && Number(row.cumulativeVolume) > 0
              ? Number(row.amount) / Number(row.cumulativeVolume) : null;
          row.vwapGap = hasNumber(row.vwap) && row.vwap > 0 && hasNumber(row.price)
            ? (row.price / row.vwap - 1) * 100 : null;
          const intervalVolume = hasNumber(row.cumulativeVolume) && previous && hasNumber(previous.cumulativeVolume)
            ? Math.max(0, row.cumulativeVolume - previous.cumulativeVolume)
            : sumOf(intervalRows, 'volume');
          const stats = samePeriodVolumeStats(
            dataset.volumeHistoryBars, session.date, start, end, intervalVolume,
            Number(tracker.store.volumeRatioDays) || 20
          );
          row.volumeRatio = stats ? stats.ratio : null;
          row.volumeRatioSample = stats ? stats.sample : 0;
          row.alpha = hasNumber(row.stockChange) && hasNumber(row.boardChange)
            ? row.stockChange - row.boardChange : null;
        }
        const after = JSON.stringify([
          row.intervalStart, row.open, row.high, row.low, row.cumulativeVolume,
          row.turnover, row.amount, row.vwap, row.vwapGap, row.volumeRatio, row.alpha,
          row.volumeSource, row.vwapIssue
        ]);
        if (before !== after) updated += 1;
      });
      return updated;
    }

    function barsInTradingInterval(bars, date, start, end) {
      return bars.filter(bar => {
        const time = bar.time.slice(0, 5);
        return bar.date === date && time > start && time <= end;
      });
    }

    function boardChangeAt(minuteData, dailyBars, date, endTime) {
      if (!minuteData || !dailyBars) return null;
      let previousClose = previousDailyClose(dailyBars, date);
      const latestDate = lastOf(minuteData.bars) && lastOf(minuteData.bars).date;
      if (!(previousClose > 0) && latestDate === date) previousClose = minuteData.previousClose;
      if (!(previousClose > 0)) return null;

      const bars = minuteData.bars.filter(bar => bar.date === date && bar.time.slice(0, 5) <= endTime);
      if (endTime === '09:30' || endTime === '13:00') {
        const openingBar = openingMinuteBar(minuteData.bars, date, endTime);
        if (openingBar && openingBar.open > 0) return (openingBar.open / previousClose - 1) * 100;
      }
      const last = lastOf(bars);
      if (minuteData.stale && (!last || last.time.slice(0, 5) < endTime)) return null;
      return last ? (last.close / previousClose - 1) * 100 : null;
    }

    function boardRetryDelay(failureCount) {
      return Math.min(5 * 60 * 1000, 30000 * Math.pow(2, Math.max(0, failureCount - 1)));
    }

    function breadthForRequestedTime(snapshot, requestedTime, source) {
      if (!snapshot || requestedTime < '09:30') return null;
      const lag = snapshot.capturedSeconds - timeToSeconds(requestedTime);
      return lag >= -2 && lag <= 150 ? snapshot : null;
    }

    function breadthRetryDelay(failureCount) {
      return Math.min(60000, 8000 * Math.pow(2, Math.max(0, failureCount - 1)));
    }

    function buildAuctionTrackerRow(session, dataset, source) {
      const previousClose = previousDailyClose(dataset.stockDailyBars, session.date);
      const nowTime = chinaTimeText(true);
      const quote = dataset.auctionQuote;
      const quoteTime = quote && quote.__capturedTime ? quote.__capturedTime : nowTime;
      const quoteIsLive = session.date === chinaToday() && quoteTime >= '09:24:50' && quoteTime < '09:30:00'
        && quote && (Number(quote.trade) > 0 || Number(quote.open) > 0);
      const openingBar = openingMinuteBar(dataset.stockBars, session.date, '09:30');
      const price = quoteIsLive
        ? (Number(quote.trade) > 0 ? Number(quote.trade) : Number(quote.open))
        : openingBar ? Number(openingBar.open) : null;
      if (!(price > 0)) {
        const error = new Error(`${session.date} 09:25 集合竞价数据尚未形成。`);
        error.code = 'SESSION_BAR_PENDING';
        error.sessionPoint = '09:25';
        throw error;
      }
      const amount = quoteIsLive && Number(quote.amount) >= 0 ? Number(quote.amount) : null;
      const cumulativeVolume = quoteIsLive
        ? normalizedTradeShares(quote.volume, amount, price, 1) : null;
      const checkedAuction = hasNumber(cumulativeVolume) && cumulativeVolume > 0 && hasNumber(amount)
        ? validatedCumulativeTradeMetrics([{
          volume: cumulativeVolume, amount, low: price, high: price, close: price
        }], [{ low: price, high: price, close: price }]) : null;
      const vwap = hasNumber(cumulativeVolume) && cumulativeVolume > 0 && hasNumber(amount) && amount > 0 ? amount / cumulativeVolume : null;
      return {
        id: createId(),
        point: `${session.date} 09:25`,
        requestedTime: '09:25',
        stockDataTime: quoteIsLive ? String(quote.ticktime || '09:25') : openingBar.time.slice(0, 5),
        auctionPoint: true,
        auctionEstimated: !quoteIsLive,
        openingPoint: false,
        openingSession: '',
        intervalStart: '09:15',
        intervalEnd: '09:25',
        source,
        scheduleTime: source === 'auto' ? '09:25' : '',
        capturedAt: chinaNowText(),
        open: price,
        high: price,
        low: price,
        price,
        cumulativeVolume,
        volumeSource: checkedAuction ? '集合竞价真实累计成交' : '',
        turnover: hasNumber(cumulativeVolume) ? cumulativeVolume / dataset.profile.floatShares * 100 : null,
        amount,
        amountTrusted: Boolean(checkedAuction),
        vwap,
        vwapLow: checkedAuction ? checkedAuction.low : null,
        vwapHigh: checkedAuction ? checkedAuction.high : null,
        vwapIssue: quoteIsLive && !checkedAuction ? '集合竞价量额待校验；VWAP仍按原始量额计算' : '',
        vwapGap: hasNumber(vwap) && vwap > 0 ? (price / vwap - 1) * 100 : null,
        volumeRatio: null,
        volumeRatioSample: 0,
        stockChange: previousClose > 0 ? (price / previousClose - 1) * 100 : null,
        boardCode: dataset.board ? dataset.board.code : '',
        boardName: dataset.board ? dataset.board.name : '',
        boardChange: null,
        alpha: null,
        boardMedianChange: null,
        boardMedianTotal: null,
        boardMedianCode: '',
        boardMedianMethod: '',
        boardMedianCapturedAt: '',
        boardMedianStatus: 'preopen',
        boardMedianPending: false,
        boardMedianError: '',
        boardPending: Boolean(dataset.board),
        ...Object.fromEntries(INDEXES.map(index => [index.key, null]))
      };
    }

    function buildFiveMinuteTrackTimes() {
      const times = ['09:25'];
      const appendRange = (startHour, startMinute, endHour, endMinute) => {
        const start = startHour * 60 + startMinute;
        const end = endHour * 60 + endMinute;
        for (let minute = start; minute <= end; minute += 5) {
          times.push(`${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`);
        }
      };
      appendRange(9, 30, 11, 30);
      appendRange(13, 5, 15, 0);
      return Object.freeze(times);
    }

    function buildRuntimeStateDocument() {
      const stocks = {};
      runtimeConfiguredItems().forEach(item => {
        const stockState = runtimeState[item.symbol];
        if (stockState && stockState.latest && stockState.latest.timestamp) {
          stocks[item.symbol] = runtimeStateStockPayload(stockState.latest, stockState.buffer.length);
        }
      });
      return { updated_at: chinaIsoText(), stocks };
    }

    function buildTrackerRow(session, dataset, requestedTime, source) {
      if (requestedTime === '09:25') return buildAuctionTrackerRow(session, dataset, source);
      const previous = trackerComparisonPrevious(session.rows, requestedTime);
      const intervalStart = trackerIntervalStart(previous, requestedTime);
      let cumulativeRows = dataset.stockBars.filter(row =>
        row.date === session.date && row.time.slice(0, 5) >= '09:30' && row.time.slice(0, 5) <= requestedTime
      );
      let endpoint = lastOf(cumulativeRows);
      let openingPoint = false;
      let openingSession = '';

      if (requestedTime === '09:30') {
        const firstBar = openingMinuteBar(dataset.stockBars, session.date, requestedTime);
        endpoint = firstBar || null;
        openingPoint = Boolean(firstBar);
        openingSession = firstBar ? requestedTime : '';
      }
      if (!endpoint) {
        const error = new Error(`${session.date} ${requestedTime} 之前没有分钟行情；非交易日或开盘前无法生成数据。`);
        if (requestedTime === '09:30' && session.date === chinaToday()) {
          error.code = 'SESSION_BAR_PENDING';
          error.sessionPoint = requestedTime;
        }
        throw error;
      }

      let intervalRows = barsInTradingInterval(dataset.stockBars, session.date, intervalStart, requestedTime);
      const currentPrice = openingPoint ? endpoint.open : endpoint.close;
      if (!intervalRows.length && !openingPoint) intervalRows = [endpoint];
      const intervalOpen = openingPoint ? currentPrice : Number(intervalRows[0]?.open || currentPrice);
      const intervalHigh = openingPoint ? currentPrice : maxOf(intervalRows, 'high');
      const intervalLow = openingPoint ? currentPrice : minOf(intervalRows, 'low');

      const tradeMetrics = cumulativeTradeMetricsForTime(
        dataset, session.date, requestedTime, source, cumulativeRows
      );
      let cumulativeVolume = tradeMetrics && hasNumber(tradeMetrics.volume) ? tradeMetrics.volume : null;
      let cumulativeAmount = tradeMetrics && hasNumber(tradeMetrics.amount) ? tradeMetrics.amount : null;
      let volumeSource = tradeMetrics ? tradeMetrics.source : '';
      const hasRealAuctionMetrics = openingPoint && previous && previous.requestedTime === '09:25'
        && !previous.auctionEstimated && hasNumber(previous.cumulativeVolume) && hasNumber(previous.amount);
      if (hasRealAuctionMetrics) {
        cumulativeVolume = previous.cumulativeVolume;
        cumulativeAmount = previous.amount;
        volumeSource = hasNumber(cumulativeVolume) && hasNumber(cumulativeAmount) ? '集合竞价真实累计成交' : '';
      }
      const currentIntervalVolume = hasNumber(cumulativeVolume) && previous && hasNumber(previous.cumulativeVolume)
        ? Math.max(0, cumulativeVolume - previous.cumulativeVolume)
        : sumOf(intervalRows, 'volume');
      const volumeStats = samePeriodVolumeStats(
        dataset.volumeHistoryBars, session.date, intervalStart, requestedTime,
        currentIntervalVolume, Number(tracker.store.volumeRatioDays) || 20
      );
      const vwap = tradeMetrics && hasNumber(tradeMetrics.vwap) ? tradeMetrics.vwap : null;
      const previousClose = previousDailyClose(dataset.stockDailyBars, session.date);
      const changes = {};
      INDEXES.forEach((index, i) => {
        changes[index.key] = indexChangeAt(
          dataset.indexMinuteBars[i], dataset.indexDailyBars[i], session.date, requestedTime
        );
      });
      const currentBoardChange = dataset.board
        ? boardChangeAt(dataset.boardMinuteData, dataset.boardDailyBars, session.date, requestedTime) : null;
      const breadth = breadthForRequestedTime(dataset.boardBreadth, requestedTime, source);
      const stockChange = previousClose > 0 ? (currentPrice / previousClose - 1) * 100 : null;
      const breadthLag = timeToSeconds(chinaTimeText(true)) - timeToSeconds(requestedTime);
      const breadthPending = Boolean(dataset.board && !breadth && requestedTime >= '09:30'
        && breadthLag >= -2 && breadthLag <= 150 && chinaTimeText(false) <= '15:05');

      return {
        id: createId(),
        point: `${session.date} ${requestedTime}`,
        requestedTime,
        stockDataTime: endpoint.time.slice(0, 5),
        auctionPoint: false,
        auctionEstimated: false,
        openingPoint,
        openingSession,
        intervalStart,
        intervalEnd: requestedTime,
        source,
        scheduleTime: source === 'auto' ? requestedTime : '',
        capturedAt: chinaNowText(),
        open: intervalOpen,
        high: intervalHigh,
        low: intervalLow,
        price: currentPrice,
        cumulativeVolume,
        volumeSource,
        turnover: hasNumber(cumulativeVolume) ? cumulativeVolume / dataset.profile.floatShares * 100 : null,
        amount: cumulativeAmount,
        amountTrusted: tradeMetrics ? tradeMetrics.amountTrusted !== false : false,
        vwap,
        vwapLow: tradeMetrics ? tradeMetrics.low : null,
        vwapHigh: tradeMetrics ? tradeMetrics.high : null,
        vwapIssue: !hasNumber(vwap) && !openingPoint
          ? (tradeMetrics && tradeMetrics.issue ? tradeMetrics.issue : '成交额/成交量暂不可用，VWAP无法计算') : '',
        vwapGap: hasNumber(vwap) && vwap > 0 ? (currentPrice / vwap - 1) * 100 : null,
        volumeRatio: volumeStats ? volumeStats.ratio : null,
        volumeRatioSample: volumeStats ? volumeStats.sample : 0,
        stockChange,
        boardCode: dataset.board ? dataset.board.code : '',
        boardName: dataset.board ? dataset.board.name : '',
        boardChange: currentBoardChange,
        alpha: hasNumber(stockChange) && hasNumber(currentBoardChange) ? stockChange - currentBoardChange : null,
        boardMedianChange: breadth ? breadth.medianChange : null,
        boardMedianTotal: breadth ? breadth.total : null,
        boardMedianCode: breadth ? breadth.boardCode : '',
        boardMedianMethod: breadth ? breadth.method : '',
        boardMedianCapturedAt: breadth ? breadth.capturedAt : '',
        boardMedianStatus: breadth ? 'ok' : breadthPending ? 'pending' : 'historical',
        boardMedianPending: breadthPending,
        boardMedianError: dataset.boardMedianError ? String(dataset.boardMedianError.message || '') : '',
        boardPending: Boolean(dataset.board && !hasNumber(currentBoardChange)),
        ...changes
      };
    }

    function cachedBoardMinuteData(board, date) {
      return tracker.boardMinuteCache.get(`${date}|${board.code}`) || null;
    }

    function canRetryBreadthRow(row) {
      if (!row || row.auctionPoint || hasNumber(row.boardMedianChange) || !row.boardCode) return false;
      if (!String(row.point || '').startsWith(chinaToday())) return false;
      const now = timeToSeconds(chinaTimeText(true));
      const target = timeToSeconds(row.requestedTime || '00:00');
      const lag = now - target;
      const marketTime = chinaTimeText(false);
      return marketTime >= '09:30' && marketTime <= '15:05' && lag >= -2 && lag <= 150;
    }

    async function captureOneTracker(item, sharedMarket, immediate) {
      const session = ensureTrackerSession(item.symbol);
      const boardProfile = await ensureTrackerBoardProfile(session, item);
      const board = getBoardByCode(boardProfile, item.boardCode);
      if (!board) throw new Error(`${item.symbol} 未能确定对比行业 / 概念指数。`);
      const dueTimes = trackerDueTimes(session);
      const needsMetricBackfill = session.rows.some(row => row.requestedTime !== '09:25'
        && (!hasNumber(row.open) || (row.requestedTime > '09:30'
          && (!hasNumber(row.cumulativeVolume) || !Object.prototype.hasOwnProperty.call(row, 'volumeSource')))));
      const hasBoardGaps = session.rows.some(row => row.requestedTime !== '09:25'
        && (row.boardCode !== board.code || !hasNumber(row.boardChange)));
      const health = getBoardHealth(board.code);
      const needsBoardBackfill = hasBoardGaps && Date.now() >= health.retryAfter;
      if (!dueTimes.length && !immediate && !needsMetricBackfill && !needsBoardBackfill) {
        return { itemId: item.id, session, board, added: 0, newRows: [], backfilled: 0, boardBackfilled: 0 };
      }
      const point = immediate ? currentTrackerPoint() : '';
      if (immediate && !point) throw new Error(`${session.stockName || item.symbol}：09:25 前暂无可追加的盘中数据。`);
      const needAuctionQuote = (dueTimes.includes('09:25') || point === '09:25') && chinaTimeText(false) < '09:30';
      const dataset = await getTrackerDataset(item.symbol, session.date, board, sharedMarket, needAuctionQuote);
      session.stockName = dataset.profile.name;
      let added = 0;
      const newRows = [];
      dueTimes.forEach(time => {
        const row = buildTrackerRow(session, dataset, time, 'auto');
        session.rows.push(row);
        newRows.push(row);
        added += 1;
      });
      if (immediate && point && !dueTimes.includes(point)
        && !session.rows.some(row => row.requestedTime === point)) {
        const row = buildTrackerRow(session, dataset, point, 'now');
        session.rows.push(row);
        newRows.push(row);
        added += 1;
      }
      session.rows.sort((a, b) => String(a.requestedTime).localeCompare(String(b.requestedTime)) || String(a.capturedAt).localeCompare(String(b.capturedAt)));
      const backfilled = backfillTrackerMetrics(session, dataset);
      const boardBackfilled = backfillTrackerBoardChanges(session, dataset);
      session.updatedAt = chinaNowText();
      return { itemId: item.id, session, board, added, newRows, backfilled, boardBackfilled, boardError: dataset.boardError };
    }

    function chinaDateParts(date = new Date()) {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Shanghai',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hourCycle: 'h23'
      }).formatToParts(date).reduce((acc, item) => {
        if (item.type !== 'literal') acc[item.type] = item.value;
        return acc;
      }, {});
      return parts;
    }

    function chinaIsoText(date = new Date()) {
      const p = chinaDateParts(date);
      return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}+08:00`;
    }

    function chinaNowText() {
      const p = chinaDateParts();
      return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
    }

    function chinaTimeText(includeSeconds = false) {
      const p = chinaDateParts();
      return includeSeconds ? `${p.hour}:${p.minute}:${p.second}` : `${p.hour}:${p.minute}`;
    }

    function chinaToday() {
      const p = chinaDateParts();
      return `${p.year}-${p.month}-${p.day}`;
    }

    async function collectRuntimeStockFields(item, indexSnapshot = null) {
      const symbol = item.symbol;
      const [bundleResult, profileResult, boardProfileResult] = await Promise.allSettled([
        getRuntimeStockBundle(symbol),
        getRuntimeProfile(symbol),
        getRuntimeBoardProfile(symbol)
      ]);
      if (bundleResult.status === 'rejected') throw bundleResult.reason;

      const bundleCache = bundleResult.value || {};
      const bundle = bundleCache.value || {};
      const cumulative = bundle.cumulative || {};
      const quote = bundle.quote || {};
      const profileCache = profileResult.status === 'fulfilled' ? profileResult.value : null;
      const profile = profileCache && profileCache.value ? profileCache.value : state.profiles[symbol] || null;
      const boardProfileCache = boardProfileResult.status === 'fulfilled' ? boardProfileResult.value : null;
      const boardProfile = boardProfileResult.status === 'fulfilled'
        ? boardProfileCache.value : state.boardProfiles[symbol] || null;
      const board = getBoardByCode(boardProfile, item.boardCode) || preferredBoard(boardProfile);
      const [industryResult, breadthResult] = await Promise.allSettled([
        getRuntimeIndustrySnapshot(board),
        getRuntimeBreadthSnapshot(board)
      ]);
      const industryCache = industryResult.status === 'fulfilled' ? industryResult.value : null;
      const breadthCache = breadthResult.status === 'fulfilled' ? breadthResult.value : null;
      const industry = industryCache && industryCache.value ? industryCache.value : null;
      const breadth = breadthCache && breadthCache.value ? breadthCache.value : null;
      const indexValues = indexSnapshot && indexSnapshot.value ? indexSnapshot.value : null;

      const price = firstRuntimePositive(quote.trade, cumulative.price, quote.open);
      if (!(price > 0)) throw new Error(`${symbol} 实时价格尚未形成。`);
      const open = firstRuntimePositive(quote.open, price);
      const high = firstRuntimePositive(quote.high, price);
      const low = firstRuntimePositive(quote.low, price);
      const quoteAmount = firstRuntimeNumber(quote.amount);
      const quoteVolume = firstRuntimeNumber(quote.volume);
      const cumulativeAmount = firstRuntimeNumber(cumulative.amount, quoteAmount);
      const cumulativeVolume = firstRuntimeNumber(
        cumulative.volume,
        hasNumber(quoteVolume) ? normalizedTradeShares(quoteVolume, cumulativeAmount, price, 1) : null
      );
      const cumulativeTurnover = profile && profile.floatShares > 0 && hasNumber(cumulativeVolume)
        ? Number(cumulativeVolume) / Number(profile.floatShares) * 100 : null;
      const vwap = hasNumber(cumulativeAmount) && Number(cumulativeAmount) > 0
        && hasNumber(cumulativeVolume) && Number(cumulativeVolume) > 0
        ? Number(cumulativeAmount) / Number(cumulativeVolume) : null;
      const previousClose = firstRuntimePositive(quote.settlement, quote.preclose, quote.prevclose);
      const stockPct = hasNumber(quote.changepercent)
        ? Number(quote.changepercent)
        : previousClose > 0 ? (price / previousClose - 1) * 100 : null;
      const industryPct = industry && hasNumber(industry.change) ? Number(industry.change) : null;
      const sourceUpdatedAt = bundleCache.source_updated_at || chinaIsoText(runtimeNow());
      const tradeSourceCapturedAt = runtimeSourceTimestampText(cumulative.capturedAt || sourceUpdatedAt);

      return {
        name: String(quote.name || (profile && profile.name) || (boardProfile && boardProfile.name) || symbol),
        price,
        open,
        high,
        low,
        cumulative_volume: cumulativeVolume,
        cumulative_amount: cumulativeAmount,
        cumulative_turnover: cumulativeTurnover,
        vwap,
        price_vwap_pct: vwap > 0 ? (price / vwap - 1) * 100 : null,
        stock_pct: stockPct,
        industry_pct: industryPct,
        alpha: hasNumber(stockPct) && hasNumber(industryPct) ? Number(stockPct) - Number(industryPct) : null,
        industry_breadth: breadth && hasNumber(breadth.medianChange) ? Number(breadth.medianChange) : null,
        sh_pct: indexValues && hasNumber(indexValues.shanghai) ? Number(indexValues.shanghai) : null,
        cyb_pct: indexValues && hasNumber(indexValues.chinext) ? Number(indexValues.chinext) : null,
        bse_pct: indexValues && hasNumber(indexValues.beijing) ? Number(indexValues.beijing) : null,
        star_pct: indexValues && hasNumber(indexValues.star) ? Number(indexValues.star) : null,
        data_status: bundleCache.data_status === 'stale' ? 'stale' : 'fresh',
        source_updated_at: sourceUpdatedAt,
        data_age_ms: runtimeDataAgeMs(sourceUpdatedAt),
        trade_source: String(cumulative.source || (bundle.quote ? '新浪实时行情列表' : '')),
        trade_source_captured_at: tradeSourceCapturedAt,
        trade_data_age_ms: runtimeDataAgeMs(tradeSourceCapturedAt)
      };
    }

    function computeRuntimeWindowFields(buffer, current) {
      const base15 = nearestRuntimeWindowSample(buffer, current, 15);
      const base30 = nearestRuntimeWindowSample(buffer, current, 30);
      const base60 = nearestRuntimeWindowSample(buffer, current, 60);
      const deltaTurnover60 = runtimeFieldDelta(current, base60, 'cumulative_turnover');
      const priceChangePct60 = base60 && hasNumber(current.price) && hasNumber(base60.price) && Number(base60.price) > 0
        ? (Number(current.price) / Number(base60.price) - 1) * 100 : null;
      return {
        delta_price_15s: runtimeFieldDelta(current, base15, 'price'),
        delta_price_30s: runtimeFieldDelta(current, base30, 'price'),
        delta_price_60s: runtimeFieldDelta(current, base60, 'price'),
        delta_volume_30s: runtimeFieldDelta(current, base30, 'cumulative_volume'),
        delta_volume_60s: runtimeFieldDelta(current, base60, 'cumulative_volume'),
        delta_amount_30s: runtimeFieldDelta(current, base30, 'cumulative_amount'),
        delta_amount_60s: runtimeFieldDelta(current, base60, 'cumulative_amount'),
        delta_turnover_30s: runtimeFieldDelta(current, base30, 'cumulative_turnover'),
        delta_turnover_60s: deltaTurnover60,
        alpha_change_30s: runtimeFieldDelta(current, base30, 'alpha'),
        alpha_change_60s: runtimeFieldDelta(current, base60, 'alpha'),
        price_efficiency_60s: hasNumber(priceChangePct60) && hasNumber(deltaTurnover60) && Math.abs(Number(deltaTurnover60)) > 1e-12
          ? Number(priceChangePct60) / Number(deltaTurnover60) : null
      };
    }

    function configuredTrackerSessions() {
      return tracker.store.watchlist.map(item => trackerSessionForItem(item)).filter(Boolean);
    }

    function createId() {
      return `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    }

    function createTrackerLedgerEvent(session, row, detail) {
      const sessionDate = session.date;
      const trackingSessionId = session.tracking_session_id || session.key;
      const sequence = eventSequenceMax(trackingSessionId) + 1;
      const event = {
        schema_version: '1.1',
        event_id: eventIdFor(trackingSessionId, sequence),
        event_seq: sequence,
        event_key: `${trackingSessionId}|${row.requestedTime}|${detail.type}`,
        tracking_session_id: trackingSessionId,
        previous_tracking_session_id: session.previous_tracking_session_id || null,
        session_date: sessionDate,
        timestamp: trackerEventTimestamp(session, row),
        detected_at: trackerEventDetectedAt(row),
        symbol: session.symbol,
        name: session.stockName || session.symbol,
        type: detail.type,
        label: detail.label,
        severity: normalizeSeverity(detail.severity),
        source: 'tracker_5m',
        price: hasNumber(row.price) ? Number(row.price) : null,
        requested_time: row.requestedTime,
        evidence: trackerEventEvidence(row)
      };
      event.actionability_at_creation = eventActionability(event);
      eventEngine.events.push(event);
      eventEngine.eventKeys.add(event.event_key);
      return event;
    }

    function cumulativeSnapshotForRequestedTime(snapshot, requestedTime, source) {
      if (!snapshot || requestedTime < '09:30' || requestedTime === '09:30') return null;
      const lag = snapshot.capturedSeconds - timeToSeconds(requestedTime);
      return lag >= -2 && lag <= 150 ? snapshot : null;
    }

    function cumulativeTradeMetricsForTime(dataset, date, requestedTime, source, priceRows) {
      // Base principle: raw market data and derived validation are two separate layers.
      // For BSE (bj): KEEP the original Sina minute-K fetch chain as the authoritative raw layer.
      // Raw volume/amount are preserved exactly as the Sina path returns them; validation only
      // decides whether amount may participate in Δamount / cumulative VWAP / interval VWAP.
      const symbol = dataset.profile && dataset.profile.symbol;
      if (isBeijingSymbol(symbol)) {
        const sinaMetrics = sinaCumulativeTradeMetrics(priceRows, symbol);
        if (sinaMetrics) return sinaMetrics;
      }

      // Non-BSE keeps the existing same-time snapshot / Eastmoney validation path.
      const snapshot = cumulativeSnapshotForRequestedTime(dataset.cumulativeSnapshot, requestedTime, source);
      if (snapshot) {
        const snapshotPrice = Number(snapshot.price);
        const low = Math.min(minOf(priceRows, 'low'), snapshotPrice > 0 ? snapshotPrice : Infinity);
        const high = Math.max(maxOf(priceRows, 'high'), snapshotPrice > 0 ? snapshotPrice : -Infinity);
        const validationPrices = snapshotPrice > 0
          ? [...priceRows, { low: snapshotPrice, high: snapshotPrice, close: snapshotPrice }] : priceRows;
        const checked = validatedCumulativeTradeMetrics([{
          volume: snapshot.volume,
          amount: snapshot.amount,
          low,
          high,
          close: snapshot.price || lastOf(priceRows)?.close
        }], validationPrices);
        if (checked) return { ...checked, source: snapshot.source || '实时累计成交', issue: '' };
      }

      const realMinuteRows = (dataset.stockTradeBars || []).filter(row =>
        row.date === date && row.time.slice(0, 5) >= '09:30' && row.time.slice(0, 5) <= requestedTime
      );
      const realMinuteMetrics = validatedCumulativeTradeMetrics(realMinuteRows, priceRows);
      if (realMinuteMetrics) {
        return { ...realMinuteMetrics, source: '东方财富真实分钟成交', issue: '' };
      }

      // Generic Sina fallback for non-BSE symbols if the preferred validated sources fail.
      const sinaMetrics = sinaCumulativeTradeMetrics(priceRows, symbol);
      if (sinaMetrics) return sinaMetrics;

      return null;
    }

    function currentTrackerPoint() {
      const current = chinaTimeText(false);
      return current >= TRACK_TIMES[0] ? current : '';
    }

    function deltaValue(current, previous) {
      return hasNumber(current) && hasNumber(previous) ? Number(current) - Number(previous) : null;
    }

    function dropTrackerStock(id, skipConfirm = false) {
      if (tracker.busy) return false;
      const item = getWatchItem(id);
      if (!item) return false;
      const session = trackerSessionForItem(item);
      const name = session && session.stockName || item.symbol || '该股票';
      if (!skipConfirm && !confirm(`确定停止跟踪并删除 ${name} 吗？\n\n本操作将删除该股票当前交易日的盘中数据、Session及当前运行状态。\n删除后不会归档。\n如稍后重新加入，将作为新的跟踪 Session 从零开始。`)) return false;
      const trackingSessionId = item.tracking_session_id;
      tracker.store.watchlist = tracker.store.watchlist.filter(value => value.id !== id);
      tracker.store.archivedWatchlist = [];
      if (trackingSessionId) delete tracker.store.sessions[trackingSessionId];
      tracker.copySelection.delete(trackingSessionId || item.symbol);
      if (tracker.store.activeKey === trackingSessionId) tracker.store.activeKey = '';
      tracker.csvHandles.delete(id);
      tracker.csvWriteQueues.delete(id);
      tracker.csvRuntimeStatus.delete(id);
      deleteCsvHandle(id).catch(() => {});
      invalidateDeletedTrackingSession(trackingSessionId, item.symbol);
      saveTrackerStore();
      renderTracker();
      showToast(`${name} 已停止跟踪并删除；当前交易日运行状态不再保留。`);
      return true;
    }

    async function eastmoneyMarketData(path, params, validate = null) {
      let lastError;
      const hosts = [tracker.eastmoneyHost, ...EASTMONEY_HOSTS]
        .filter((host, index, values) => host && values.indexOf(host) === index)
        .sort((a, b) => Number(a.includes('push2delay.')) - Number(b.includes('push2delay.')));
      const requestParams = { ut: EASTMONEY_TOKEN, ...params };
      for (const host of hosts) {
        try {
          const value = await loadJsonpCallback(`${host}${path}`, requestParams, 'cb', 4500);
          if (!value || Number(value.rc) !== 0 || !value.data) {
            throw new Error('东方财富没有返回所选板块的行情数据。');
          }
          if (validate && !validate(value.data)) {
            throw new Error('东方财富暂未返回所选板块的完整行情，正在尝试备用接口。');
          }
          tracker.eastmoneyHost = host;
          value.data.__eastmoneyHost = host;
          value.data.__delayedHost = host.includes('push2delay.');
          return value.data;
        } catch (error) {
          lastError = error;
        }
      }
      tracker.eastmoneyHost = '';
      const error = lastError || new Error('无法获取东方财富板块行情。');
      error.boardHostsFailed = true;
      throw error;
    }

    function eastmoneyStockSecid(symbol) {
      // Eastmoney uses market id 1 for Shanghai, 0 for Shenzhen and most Beijing/NEEQ codes.
      // Beijing coverage on stock-level trends/snapshot endpoints is less stable than Sina,
      // so BSE uses this only as an auxiliary source; the main BSE fallback is Sina minute K-line.
      return `${String(symbol || '').toLowerCase().startsWith('sh') ? '1' : '0'}.${String(symbol || '').slice(2)}`;
    }

    function emptyAnalysisState() {
      return { schema_version: '1.1', updated_at: null, tracking_sessions: {} };
    }

    function emptyDecisionCheckpoint() {
      return {
        schema_version: '1.1',
        updated_at: null,
        analyzed_at: null,
        checkpoint_id: null,
        covered_handoff_id: null,
        tracking_sessions: {}
      };
    }

    function ensureAllTrackingSessionCursors() {
      let created = 0;
      configuredTrackerSessions().forEach(session => {
        if (ensureAnalysisCursorForSession(session)) created += 1;
      });
      if (created) saveEventEngineStore();
      return created;
    }

    function ensureAnalysisCursorForSession(session) {
      if (!session || !session.tracking_session_id) return false;
      eventEngine.analysisState = normalizeAnalysisState(eventEngine.analysisState);
      if (eventEngine.analysisState.tracking_sessions[session.tracking_session_id]) return false;
      eventEngine.analysisState.tracking_sessions[session.tracking_session_id] = {
        tracking_session_id: session.tracking_session_id,
        symbol: session.symbol,
        session_date: session.date,
        last_processed_event_seq: 0,
        last_processed_event_id: null,
        last_processed_observation_time: null,
        last_analyzed_at: null,
        checkpoint_id: null,
        covered_handoff_id: null
      };
      eventEngine.analysisState.updated_at = eventIsoText();
      return true;
    }

    function ensureRuntimeStockState(symbol) {
      if (!runtimeState[symbol]) {
        runtimeState[symbol] = {
          latest: {},
          buffer: [],
          lastArchiveAt: null,
          archiveAnchorAt: null,
          initializedAt: chinaIsoText(runtimeNow()),
          inFlight: false
        };
      }
      return runtimeState[symbol];
    }

    async function ensureTrackerBoardProfile(session, item, force = false) {
      const profile = await getStockBoards(session.symbol, force);
      const board = getBoardByCode(profile, item.boardCode)
        || getBoardByCode(profile, session.selectedBoardCode)
        || preferredBoard(profile);
      item.boardCode = board ? board.code : '';
      session.selectedBoardCode = item.boardCode;
      saveTrackerStore();
      return profile;
    }

    function ensureTrackerSession(symbol, preferredItem = null) {
      const date = chinaToday();
      const item = preferredItem || tracker.store.watchlist.find(value => value.symbol === symbol);
      let trackingSessionId = item && item.tracking_session_id;
      const existing = trackingSessionId && tracker.store.sessions[trackingSessionId];
      const existingIsCurrent = existing && existing.date === date && existing.symbol === symbol;
      const reservedSequence = !existing ? trackingSessionSequenceFor(trackingSessionId, symbol, date) : 0;
      if (!trackingSessionId || (existing && !existingIsCurrent) || (!existing && !reservedSequence)) {
        if (!item) throw new Error(`${symbol} 尚未加入当前观察池。`);
        trackingSessionId = assignTrackingSessionToItem(item, symbol);
      } else if (!existing && reservedSequence) {
        tracker.store.session_seq_by_symbol = tracker.store.session_seq_by_symbol || {};
        const counterKey = `${date}|${symbol}`;
        tracker.store.session_seq_by_symbol[counterKey] = Math.max(
          Number(tracker.store.session_seq_by_symbol[counterKey]) || 0,
          reservedSequence
        );
      }
      if (!tracker.store.sessions[trackingSessionId]) {
        const start = {
          started_at: item && item.tracking_started_at || chinaIsoText(),
          start_requested_time: item && Object.prototype.hasOwnProperty.call(item, 'tracking_start_requested_time')
            ? item.tracking_start_requested_time : nextTrackerStartRequestedTime()
        };
        tracker.store.sessions[trackingSessionId] = {
          key: trackingSessionId,
          tracking_session_id: trackingSessionId,
          trackingSessionId,
          previous_tracking_session_id: item && item.previous_tracking_session_id || null,
          lifecycle_status: normalizedTrackingStatus(item && item.lifecycle_status),
          date,
          symbol,
          stockName: '',
          selectedBoardCode: '',
          started_at: start.started_at,
          start_requested_time: start.start_requested_time,
          createdAt: chinaNowText(),
          updatedAt: '',
          rows: []
        };
      }
      tracker.store.activeKey = trackingSessionId;
      saveTrackerStore();
      return tracker.store.sessions[trackingSessionId];
    }

    function eventActionability(event) {
      if (event.actionability === 'SUPERSEDED') return 'SUPERSEDED';
      if (event.session_date !== eventToday()) return 'EXPIRED';
      const timestamp = Date.parse(event.timestamp);
      const age = Number.isFinite(timestamp) ? eventNow().getTime() - timestamp : Infinity;
      return age >= 0 && age <= EVENT_RECENT_CONTEXT_MINUTES * 60000 ? 'LIVE' : 'EXPIRED';
    }

    function eventDefinition(label) {
      const normalized = String(label || '').trim();
      return EVENT_DEFINITIONS[normalized] || {
        type: `TAG_${normalized.replace(/[^A-Za-z0-9\u4e00-\u9fa5]+/g, '_').toUpperCase() || 'UNKNOWN'}`,
        severity: 'INFO'
      };
    }

    function eventDetailsForRow(row) {
      if (Array.isArray(row && row.eventDetails) && row.eventDetails.length) {
        return row.eventDetails.map(detail => ({
          label: String(detail.label || ''),
          type: String(detail.type || eventDefinition(detail.label).type),
          severity: normalizeSeverity(detail.severity || eventDefinition(detail.label).severity)
        })).filter(detail => detail.label)
          .sort((a, b) => EVENT_SEVERITY_ORDER[b.severity] - EVENT_SEVERITY_ORDER[a.severity]);
      }
      return (Array.isArray(row && row.eventTags) ? row.eventTags : []).map(label => ({
        label: String(label),
        ...eventDefinition(label)
      })).sort((a, b) => EVENT_SEVERITY_ORDER[b.severity] - EVENT_SEVERITY_ORDER[a.severity]);
    }

    function eventIdFor(trackingSessionId, sequence) {
      return `E-${trackingSessionId}-${String(sequence).padStart(4, '0')}`;
    }

    function eventIsoText() {
      return chinaIsoText(eventNow());
    }

    function eventKeyFromEvent(event) {
      const trackingSessionId = String(event && event.tracking_session_id || '');
      const date = String(event && event.session_date || '').replace(/-/g, '');
      const symbol = String(event && event.symbol || '');
      const requestedTime = String(event && event.requested_time || '');
      const type = String(event && event.type || '');
      if (trackingSessionId && requestedTime && type) return `${trackingSessionId}|${requestedTime}|${type}`;
      return date && symbol && requestedTime && type ? `${date}|${symbol}|${requestedTime}|${type}` : '';
    }

    function eventNow() {
      const supplied = eventEngine.testNowProvider ? eventEngine.testNowProvider() : new Date();
      const date = supplied instanceof Date ? supplied : new Date(supplied);
      return Number.isFinite(date.getTime()) ? date : new Date();
    }

    function eventSequenceMax(trackingSessionId, events = eventEngine.events) {
      return events.filter(event => event.tracking_session_id === trackingSessionId)
        .reduce((max, event) => Math.max(max, Number(event.event_seq) || 0), 0);
    }

    function eventToday() {
      const p = chinaDateParts(eventNow());
      return `${p.year}-${p.month}-${p.day}`;
    }

    async function fetchBoardBreadthConstituents(board) {
      const data = await eastmoneyMarketData('/api/qt/clist/get', {
        pn: '1',
        pz: '1000',
        po: '1',
        np: '1',
        fltt: '2',
        invt: '2',
        fid: 'f3',
        fs: `b:${board.code} f:!50`,
        fields: 'f3,f12,f14'
      }, value => Array.isArray(value.diff) && value.diff.length > 0);
      if (data.__delayedHost) throw new Error(`${board.name} 成分股统计仅返回延迟快照。`);
      const changes = (data.diff || []).map(item => Number(item.f3)).filter(Number.isFinite);
      const medianChange = numericMedian(changes);
      if (!hasNumber(medianChange) || !changes.length) {
        throw new Error(`${board.name}（${board.code}）成分股快照暂不可用。`);
      }
      return { medianChange, total: changes.length, method: '逐只成分股实时中位数' };
    }

    async function findCurrentQuote(symbol) {
      const cached = tracker.currentQuoteCache.get(`sina|${symbol}`);
      if (cached && Date.now() - cached.fetchedAt < 5000) return cached.data;
      const node = nodeForSymbol(symbol);
      const countValue = await getMarketData('Market_Center.getHQNodeStockCount', { node });
      const pageCount = Math.max(1, Math.ceil(Number(countValue) / 100));
      let low = 1;
      let high = pageCount;

      while (low <= high) {
        const page = Math.floor((low + high) / 2);
        const rows = await getMarketData('Market_Center.getHQNodeData', {
          page: String(page), num: '100', sort: 'symbol', asc: '1', node, symbol: '', _s_r_a: 'init'
        });
        if (!Array.isArray(rows) || rows.length === 0) break;
        const found = rows.find(row => String(row.symbol).toLowerCase() === symbol);
        if (found) {
          tracker.currentQuoteCache.set(`sina|${symbol}`, { data: found, fetchedAt: Date.now() });
          return found;
        }
        const first = String(rows[0].symbol).toLowerCase();
        const last = String(rows[rows.length - 1].symbol).toLowerCase();
        if (symbol < first) high = page - 1;
        else if (symbol > last) low = page + 1;
        else break;
      }
      throw new Error(`没有在新浪行情列表中找到 ${symbol}，请确认股票代码和市场。`);
    }

    function firstRuntimeNumber(...values) {
      const found = values.find(value => hasNumber(value));
      return typeof found === 'undefined' ? null : Number(found);
    }

    function firstRuntimePositive(...values) {
      const found = values.find(value => hasNumber(value) && Number(value) > 0);
      return typeof found === 'undefined' ? null : Number(found);
    }

    function firstSuccessful(promises) {
      return new Promise((resolve, reject) => {
        let pending = promises.length;
        let lastError = null;
        promises.forEach(promise => Promise.resolve(promise).then(resolve).catch(error => {
          lastError = error;
          pending -= 1;
          if (!pending) reject(lastError || new Error('实时累计成交数据不可用。'));
        }));
      });
    }

    function formalTrackerRows(rows) {
      return (Array.isArray(rows) ? rows : []).filter(row => row.requestedTime === '09:25'
        || TRACK_TIMES.includes(row.requestedTime));
    }

    async function getBoardBreadth(board, force = false) {
      const cached = tracker.boardBreadthCache.get(board.code);
      if (!force && cached && Date.now() - cached.fetchedAt < 20000) return cached;
      const health = getBreadthHealth(board.code);
      if (!force && Date.now() < health.retryAfter) {
        const waiting = new Error(`${board.name} 行业宽度正在等待独立重试。`);
        waiting.code = 'BREADTH_RETRY_WAIT';
        waiting.retryAt = health.retryAfter;
        throw waiting;
      }
      try {
        const stats = await fetchBoardBreadthConstituents(board);
        const result = {
          boardCode: board.code,
          medianChange: stats.medianChange,
          total: stats.total,
          method: stats.method,
          capturedAt: chinaNowText(),
          capturedSeconds: timeToSeconds(chinaTimeText(true)),
          fetchedAt: Date.now()
        };
        tracker.boardBreadthCache.set(board.code, result);
        health.failureCount = 0;
        health.retryAfter = 0;
        return result;
      } catch (error) {
        health.failureCount += 1;
        health.retryAfter = Date.now() + breadthRetryDelay(health.failureCount);
        error.message = `${board.name} 行业成分股中位数获取失败：${error.message || ''}`;
        error.code = 'BREADTH_UNAVAILABLE';
        error.retryAt = health.retryAfter;
        throw error;
      }
    }

    function getBoardByCode(profile, code) {
      return profile && profile.boards.find(board => board.code === code) || null;
    }

    function getBoardHealth(code) {
      if (!tracker.boardHealth.has(code)) {
        tracker.boardHealth.set(code, { failureCount: 0, retryAfter: 0 });
      }
      return tracker.boardHealth.get(code);
    }

    async function getBoardMinuteData(board, date = chinaToday(), force = false) {
      const cached = cachedBoardMinuteData(board, date);
      const health = getBoardHealth(board.code);
      if (!force && Date.now() < health.retryAfter) {
        if (cached) return { ...cached, stale: true, retryAt: health.retryAfter };
        const retryTime = new Intl.DateTimeFormat('zh-CN', {
          timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
        }).format(new Date(health.retryAfter));
        const waiting = new Error(`板块接口暂时休息，${retryTime} 后自动重试。`);
        waiting.code = 'BOARD_RETRY_WAIT';
        waiting.retryAt = health.retryAfter;
        throw waiting;
      }

      try {
        const data = await eastmoneyMarketData('/api/qt/stock/trends2/get', {
          secid: `90.${board.code}`,
          fields1: 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11',
          fields2: 'f51,f52,f53,f54,f55,f56,f57,f58',
          ndays: date === chinaToday() ? '1' : '5',
          iscr: '0',
          iscca: '0'
        }, value => Array.isArray(value.trends) && value.trends.length > 0);
        const bars = (data.trends || []).map(line => {
          const parts = String(line).split(',');
          const [barDate, time] = String(parts[0] || '').split(' ');
          return {
            date: barDate,
            time: `${time || '15:00'}:00`,
            open: Number(parts[1]),
            close: Number(parts[2]),
            high: Number(parts[3]),
            low: Number(parts[4]),
            volume: Number(parts[5]) || 0,
            amount: Number(parts[6]) || 0
          };
        }).filter(bar => bar.date && bar.close > 0);
        if (!bars.length) throw new Error(`${board.name}（${board.code}）没有可用的板块分钟行情。`);
        const result = {
          bars,
          previousClose: Number(data.preClose) || null,
          name: String(data.name || board.name),
          stale: Boolean(data.__delayedHost),
          delayedHost: Boolean(data.__delayedHost),
          fetchedAt: Date.now()
        };
        tracker.boardMinuteCache.set(`${date}|${board.code}`, result);
        health.failureCount = 0;
        health.retryAfter = 0;
        return result;
      } catch (error) {
        health.failureCount += 1;
        health.retryAfter = Date.now() + boardRetryDelay(health.failureCount);
        error.boardUnavailable = true;
        error.retryAt = health.retryAfter;
        if (cached) return { ...cached, stale: true, retryAt: health.retryAfter, fetchError: error.message };
        throw error;
      }
    }

    function getBreadthHealth(code) {
      if (!tracker.breadthHealth.has(code)) {
        tracker.breadthHealth.set(code, { failureCount: 0, retryAfter: 0 });
      }
      return tracker.breadthHealth.get(code);
    }

    async function getCumulativeStockSnapshot(symbol, force = false) {
      const cached = tracker.currentQuoteCache.get(`metrics|${symbol}`);
      if (!force && cached && Date.now() - cached.fetchedAt < 8000) return cached.data;
      // BSE: prefer Sina, because the Sina hs_bjs quote/minute chain is the known-stable route.
      // Shanghai/Shenzhen: keep Eastmoney first, Sina as fallback.
      const sources = isBeijingSymbol(symbol)
        ? [getSinaCumulativeSnapshot(symbol), getEastmoneyCumulativeSnapshot(symbol)]
        : [getEastmoneyCumulativeSnapshot(symbol), getSinaCumulativeSnapshot(symbol)];
      const data = await firstSuccessful(sources);
      tracker.currentQuoteCache.set(`metrics|${symbol}`, { data, fetchedAt: Date.now() });
      return data;
    }

    async function getEastmoneyCumulativeSnapshot(symbol) {
      const data = await eastmoneyMarketData('/api/qt/stock/get', {
        secid: eastmoneyStockSecid(symbol),
        invt: '2',
        fltt: '2',
        fields: 'f2,f5,f6,f8'
      }, value => Number(value.f5) >= 0 && Number(value.f6) >= 0);
      if (data.__delayedHost) throw new Error(`${symbol} 实时累计成交仅返回延迟节点。`);
      const price = Number(data.f2);
      const amount = Number(data.f6);
      const volume = normalizedTradeShares(data.f5, amount, price, 100);
      if (!(volume > 0) || !(amount > 0)) throw new Error(`${symbol} 累计成交量尚未形成。`);
      return {
        volume,
        amount,
        price,
        capturedAt: chinaNowText(),
        capturedSeconds: timeToSeconds(chinaTimeText(true)),
        source: '东方财富实时累计成交'
      };
    }

    async function getKline(symbol, scale, datalen = 1023) {
      const variable = nextJsonpName();
      const params = new URLSearchParams({
        symbol,
        scale: String(scale),
        ma: 'no',
        datalen: String(datalen),
        _: String(Date.now())
      });
      const url = `https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20${variable}=/CN_MarketDataService.getKLineData?${params}`;
      const value = await loadJsonpVariable(url, variable);
      if (!Array.isArray(value)) throw new Error(`${symbol} K线数据不可用。`);
      return normalizeBars(value);
    }

    async function getMarketData(method, params) {
      const variable = nextJsonpName();
      const query = new URLSearchParams({ ...params, _: String(Date.now()) });
      const url = `https://vip.stock.finance.sina.com.cn/quotes_service/api/jsonp_v2.php/var%20${variable}=/${method}?${query}`;
      return loadJsonpVariable(url, variable);
    }

    async function getRuntimeBoardProfile(symbol) {
      return runtimeCachedFetch(runtimeCache.boardProfiles, symbol, RUNTIME_CACHE_TTL.daily, () => getStockBoards(symbol));
    }

    async function getRuntimeBreadthSnapshot(board) {
      if (!board) return null;
      return runtimeCachedFetch(runtimeCache.breadth, board.code, RUNTIME_CACHE_TTL.breadth, () => getBoardBreadth(board, true));
    }

    async function getRuntimeIndexSnapshot() {
      return runtimeCachedFetch(runtimeCache.indexes, chinaToday(), RUNTIME_CACHE_TTL.indexes, async () => {
        const market = await getSharedTrackerMarketData(chinaToday());
        const point = chinaTimeText(false);
        const values = {};
        INDEXES.forEach((index, position) => {
          values[index.key] = indexChangeAt(
            market.indexMinuteBars[position], market.indexDailyBars[position], chinaToday(), point
          );
        });
        return values;
      });
    }

    async function getRuntimeIndustrySnapshot(board) {
      if (!board) return null;
      return runtimeCachedFetch(runtimeCache.industry, board.code, RUNTIME_CACHE_TTL.industry, async () => {
        const minuteData = await getBoardMinuteData(board, chinaToday(), true);
        return {
          board,
          change: boardChangeAt(minuteData, [], chinaToday(), chinaTimeText(false)),
          sourceUpdatedAt: minuteData.fetchedAt || Date.now()
        };
      });
    }

    async function getRuntimeProfile(symbol) {
      return runtimeCachedFetch(runtimeCache.profiles, symbol, RUNTIME_CACHE_TTL.daily, () => getStockProfile(symbol));
    }

    async function getRuntimeStockBundle(symbol) {
      return runtimeCachedFetch(runtimeCache.stock, symbol, RUNTIME_CACHE_TTL.stock, async () => {
        const cumulativePromise = isBeijingSymbol(symbol)
          ? getSinaCumulativeSnapshot(symbol).catch(() => getEastmoneyCumulativeSnapshot(symbol))
          : getEastmoneyCumulativeSnapshot(symbol).catch(() => getSinaCumulativeSnapshot(symbol));
        let cumulativeResult;
        let quoteResult;
        if (isBeijingSymbol(symbol)) {
          [cumulativeResult] = await Promise.allSettled([cumulativePromise]);
          [quoteResult] = await Promise.allSettled([findCurrentQuote(symbol)]);
        } else {
          [cumulativeResult, quoteResult] = await Promise.allSettled([cumulativePromise, findCurrentQuote(symbol)]);
        }
        if (cumulativeResult.status === 'rejected' && quoteResult.status === 'rejected') {
          throw cumulativeResult.reason || quoteResult.reason || new Error(`${symbol} 实时行情不可用。`);
        }
        return {
          cumulative: cumulativeResult.status === 'fulfilled' ? cumulativeResult.value : null,
          quote: quoteResult.status === 'fulfilled' ? quoteResult.value : null
        };
      });
    }

    async function getSharedTrackerMarketData(date) {
      const cacheKey = `${date}|indexes`;
      let dailyPromise = tracker.dailyCache.get(cacheKey);
      if (!dailyPromise) {
        dailyPromise = Promise.all(INDEXES.map(index => getKline(index.symbol, 240, 40).catch(() => [])));
        tracker.dailyCache.set(cacheKey, dailyPromise);
      }
      const [indexMinuteBars, indexDailyBars] = await Promise.all([
        Promise.all(INDEXES.map(index => getKline(index.symbol, 1, 1023).catch(() => []))),
        dailyPromise
      ]);
      return { indexMinuteBars, indexDailyBars };
    }

    async function getSinaCumulativeSnapshot(symbol) {
      const quote = await findCurrentQuote(symbol);
      const price = Number(quote.trade || quote.open);
      const amount = Number(quote.amount);
      const volume = normalizedTradeShares(quote.volume, amount, price, 1);
      if (!(volume > 0) || !(amount > 0)) throw new Error(`${symbol} 累计成交量尚未形成。`);
      return {
        volume,
        amount,
        price,
        capturedAt: chinaNowText(),
        capturedSeconds: timeToSeconds(chinaTimeText(true)),
        source: '新浪实时累计成交'
      };
    }

    async function getStockBoards(symbol, force = false) {
      const cached = state.boardProfiles[symbol];
      if (!force && cached && cached.cachedDate === chinaToday() && Array.isArray(cached.boards) && cached.boards.length) {
        return cached;
      }

      const securityCode = `${symbol.slice(2)}.${symbol.slice(0, 2).toUpperCase()}`;
      const filter = `(SECUCODE="${securityCode}")`;
      let response;
      try {
        response = await loadJsonpCallback('https://datacenter-web.eastmoney.com/api/data/v1/get', {
          reportName: 'RPT_F10_CORETHEME_BOARDTYPE',
          columns: 'ALL',
          filter,
          source: 'WEB',
          client: 'WEB'
        }, 'callback');
      } catch (_) {
        response = await loadJsonpCallback('https://datacenter.eastmoney.com/securities/api/data/get', {
          type: 'RPT_F10_CORETHEME_BOARDTYPE',
          sty: 'ALL',
          filter,
          source: 'HSF10',
          client: 'PC'
        }, 'callback');
      }

      const rows = response && response.result && Array.isArray(response.result.data)
        ? response.result.data : [];
      if (!rows.length) throw new Error(`未找到 ${securityCode} 的所属行业 / 概念，无法安全判断对比板块。`);

      const boards = rows.map(row => {
        const code = String(row.NEW_BOARD_CODE || `BK${String(row.BOARD_CODE || '').padStart(4, '0')}`).toUpperCase();
        const kind = row.BOARD_TYPE === '行业' ? 'industry'
          : row.BOARD_TYPE === '板块' ? 'region' : 'concept';
        return {
          code,
          name: String(row.BOARD_NAME || '').trim(),
          kind,
          level: Number(row.BOARD_LEVEL) || 0,
          rank: Number(row.BOARD_RANK) || 999
        };
      }).filter(board => /^BK\d+$/.test(board.code) && board.name)
        .sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name, 'zh-CN'));

      if (!boards.length) throw new Error(`${securityCode} 所属板块没有可核对的指数代码。`);
      const profile = {
        symbol,
        name: String(rows[0].SECURITY_NAME_ABBR || symbol),
        source: '东方财富行业 / 概念分类',
        boards,
        industries: boards.filter(board => board.kind === 'industry').sort((a, b) => a.level - b.level),
        concepts: boards.filter(board => board.kind === 'concept'),
        regions: boards.filter(board => board.kind === 'region'),
        cachedDate: chinaToday(),
        cachedAt: chinaNowText()
      };
      state.boardProfiles[symbol] = profile;
      saveBoardProfiles();
      return profile;
    }

    async function getStockProfile(symbol) {
      const cached = state.profiles[symbol];
      if (cached && cached.floatShares > 0 && cached.name && cached.cachedDate === chinaToday()) return cached;
      let quote;
      try {
        quote = await findCurrentQuote(symbol);
      } catch (error) {
        if (cached && cached.floatShares > 0 && cached.name) return cached;
        throw error;
      }
      const volume = Number(quote.volume);
      const turnover = Number(quote.turnoverratio);
      const trade = Number(quote.trade);
      const nmc = Number(quote.nmc);
      let floatShares = 0;
      if (volume > 0 && turnover > 0) floatShares = volume / (turnover / 100);
      else if (nmc > 0 && trade > 0) floatShares = nmc * 10000 / trade;
      if (!(floatShares > 0) && cached && cached.floatShares > 0) floatShares = cached.floatShares;
      if (!(floatShares > 0)) throw new Error('无法取得该股票流通股本，暂时不能计算换手率。');
      const profile = {
        symbol,
        code: symbol.slice(2),
        name: String(quote.name || symbol),
        floatShares,
        cachedDate: chinaToday(),
        cachedAt: chinaNowText()
      };
      state.profiles[symbol] = profile;
      saveProfiles();
      return profile;
    }

    async function getStockTradeMinuteData(symbol, date = chinaToday(), force = false) {
      const key = `${date}|${symbol}`;
      const cached = tracker.stockTradeCache.get(key);
      if (!force && cached && Date.now() - cached.fetchedAt < 12000) return cached;
      const data = await eastmoneyMarketData('/api/qt/stock/trends2/get', {
        secid: eastmoneyStockSecid(symbol),
        fields1: 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11',
        fields2: 'f51,f52,f53,f54,f55,f56,f57,f58',
        ndays: date === chinaToday() ? '1' : '5',
        iscr: '0',
        iscca: '0'
      }, value => Array.isArray(value.trends) && value.trends.length > 0);
      const bars = (data.trends || []).map(line => {
        const parts = String(line).split(',');
        const [barDate, time] = String(parts[0] || '').split(' ');
        const close = Number(parts[2]);
        const amount = Number(parts[6]);
        return {
          date: barDate,
          time: `${time || '15:00'}:00`,
          open: Number(parts[1]),
          close,
          high: Number(parts[3]),
          low: Number(parts[4]),
          volume: normalizedTradeShares(parts[5], amount, close, 100),
          amount
        };
      }).filter(bar => bar.date && bar.close > 0);
      if (!bars.length) throw new Error(`${symbol} 没有可用的真实分钟成交量。`);
      const result = { bars, fetchedAt: Date.now(), source: '东方财富真实分钟成交' };
      tracker.stockTradeCache.set(key, result);
      return result;
    }

    async function fetchTrackerDatasetNative(symbol, date, board = null, sharedMarket = null, needAuctionQuote = false) {
      const stockDailyKey = `${date}|${symbol}|daily`;
      let stockDailyPromise = tracker.dailyCache.get(stockDailyKey);
      if (!stockDailyPromise) {
        stockDailyPromise = getKline(symbol, 240, 40).catch(error => {
          tracker.dailyCache.delete(stockDailyKey);
          throw error;
        });
        tracker.dailyCache.set(stockDailyKey, stockDailyPromise);
      }
      const boardMinutePromise = board
        ? getBoardMinuteData(board, date)
          .then(data => ({ data, error: data.fetchError ? new Error(data.fetchError) : null }))
          .catch(error => ({ data: null, error }))
        : Promise.resolve({ data: null, error: null });
      const marketTime = chinaTimeText(false);
      const boardBreadthPromise = board && marketTime >= '09:30' && marketTime <= '15:05'
        ? getBoardBreadth(board)
          .then(data => ({ data, error: null }))
          .catch(error => ({ data: null, error }))
        : Promise.resolve({ data: null, error: null });
      const stockTradePromise = getStockTradeMinuteData(symbol, date)
        .then(data => ({ data, error: null }))
        .catch(error => ({ data: null, error }));
      const cumulativeSnapshotPromise = date === chinaToday() && marketTime >= '09:25' && marketTime <= '15:05'
        ? getCumulativeStockSnapshot(symbol)
          .then(data => ({ data, error: null }))
          .catch(error => ({ data: null, error }))
        : Promise.resolve({ data: null, error: null });
      const volumeHistoryPromise = getVolumeHistory(symbol)
        .then(data => ({ data, error: null }))
        .catch(error => ({ data: [], error }));
      const auctionQuotePromise = needAuctionQuote
        ? findCurrentQuote(symbol).then(quote => ({
          ...quote,
          __capturedTime: chinaTimeText(true),
          __capturedSeconds: timeToSeconds(chinaTimeText(true))
        })).catch(() => null) : Promise.resolve(null);
      const marketPromise = sharedMarket ? Promise.resolve(sharedMarket) : getSharedTrackerMarketData(date);

      const [profile, stockBars, stockDailyBars, volumeHistoryResult, market, boardResult, breadthResult,
        stockTradeResult, cumulativeSnapshotResult, auctionQuote] = await Promise.all([
        getStockProfile(symbol),
        getKline(symbol, 1, 1023),
        stockDailyPromise,
        volumeHistoryPromise,
        marketPromise,
        boardMinutePromise,
        boardBreadthPromise,
        stockTradePromise,
        cumulativeSnapshotPromise,
        auctionQuotePromise
      ]);

      return {
        profile,
        stockBars,
        stockDailyBars,
        volumeHistoryBars: volumeHistoryResult.data,
        volumeHistoryError: volumeHistoryResult.error,
        indexMinuteBars: market.indexMinuteBars,
        indexDailyBars: market.indexDailyBars,
        board,
        boardMinuteData: boardResult.data,
        boardDailyBars: [],
        boardError: boardResult.error,
        boardBreadth: breadthResult.data,
        boardMedianError: breadthResult.error,
        stockTradeBars: stockTradeResult.data ? stockTradeResult.data.bars : [],
        stockTradeError: stockTradeResult.error,
        cumulativeSnapshot: cumulativeSnapshotResult.data,
        cumulativeSnapshotError: cumulativeSnapshotResult.error,
        auctionQuote
      };
    }

    function getVolumeHistory(symbol) {
      const key = `${chinaToday()}|${symbol}`;
      if (!tracker.volumeHistoryCache.has(key)) {
        const promise = getKline(symbol, 5, 1023).then(rows => rows.map(row => ({
          ...row,
          // Keep historical/current interval volume in the same unit (shares), especially
          // across SH/SZ/BJ where public endpoints may expose volume in shares or lots.
          volume: normalizedTradeShares(row.volume, row.amount, row.close, 1)
        }))).catch(error => {
          tracker.volumeHistoryCache.delete(key);
          throw error;
        });
        tracker.volumeHistoryCache.set(key, promise);
      }
      return tracker.volumeHistoryCache.get(key);
    }

    function getWatchItem(id) {
      return tracker.store.watchlist.find(item => item.id === id) || null;
    }

    function handoffContainsTrackingSession(handoff, trackingSessionId) {
      return handoffTrackingSessionIds(handoff).has(trackingSessionId);
    }

    function handoffTrackingSessionIds(handoff) {
      const ids = new Set(Object.keys(handoff && handoff.cursor_snapshot || {}));
      (Array.isArray(handoff && handoff.selected_tracking_sessions) ? handoff.selected_tracking_sessions : [])
        .forEach(item => {
          if (item && item.tracking_session_id) ids.add(item.tracking_session_id);
        });
      return ids;
    }

    function hasNumber(value) {
      return value !== null && value !== '' && typeof value !== 'undefined' && Number.isFinite(Number(value));
    }

    function indexChangeAt(minuteBars, dailyBars, date, endTime) {
      const rows = minuteBars.filter(row => row.date === date && row.time.slice(0, 5) <= endTime);
      const last = lastOf(rows);
      const previousClose = previousDailyClose(dailyBars, date);
      if (!(previousClose > 0)) return null;
      if (endTime === '09:30' || endTime === '13:00') {
        const openingBar = openingMinuteBar(minuteBars, date, endTime);
        if (openingBar && openingBar.open > 0) return (openingBar.open / previousClose - 1) * 100;
      }
      if (last) return (last.close / previousClose - 1) * 100;
      return null;
    }

    function invalidateDeletedTrackingSession(trackingSessionId, symbol) {
      if (symbol) {
        delete runtimeState[symbol];
        runtimeCache.stock.delete(symbol);
        tracker.stockTradeCache.delete(symbol);
        tracker.currentQuoteCache.delete(symbol);
        tracker.runningSymbols = tracker.runningSymbols.filter(value => value !== symbol);
      }
      runtimeMonitor.generation += 1;
      eventEngine.events = eventEngine.events.filter(event => event.tracking_session_id !== trackingSessionId);
      if (eventEngine.analysisState && eventEngine.analysisState.tracking_sessions) {
        delete eventEngine.analysisState.tracking_sessions[trackingSessionId];
        eventEngine.analysisState.updated_at = eventIsoText();
      }
      if (eventEngine.decisionCheckpoint && eventEngine.decisionCheckpoint.tracking_sessions) {
        delete eventEngine.decisionCheckpoint.tracking_sessions[trackingSessionId];
        if (!Object.keys(eventEngine.decisionCheckpoint.tracking_sessions).length) {
          eventEngine.decisionCheckpoint = emptyDecisionCheckpoint();
        } else {
          eventEngine.decisionCheckpoint.updated_at = eventIsoText();
        }
      }
      eventEngine.handoffHistory = (eventEngine.handoffHistory || [])
        .filter(handoff => !handoffContainsTrackingSession(handoff, trackingSessionId));
      if (handoffContainsTrackingSession(eventEngine.activeHandoff, trackingSessionId)) {
        eventEngine.activeHandoff = null;
      }
      clearPendingAckUi();
      rebuildEventRuntimeKeys();
      saveEventEngineStore();
    }

    function isBeijingSymbol(symbol) {
      return String(symbol || '').toLowerCase().startsWith('bj');
    }

    function isFiveMinuteBoundary(time) {
      const parts = String(time || '').split(':');
      return parts.length >= 2 && Number(parts[1]) % 5 === 0;
    }

    function isRuntimeTradingSession(date = runtimeNow()) {
      return runtimeTradingSessionInfo(date).active;
    }

    function lastOf(rows) {
      return rows.length ? rows[rows.length - 1] : null;
    }

    function legacyCursorTrackingSessionId(symbol, sessionDate) {
      const sessions = Object.values(tracker.store.sessions || {}).filter(session =>
        session.symbol === symbol && session.date === sessionDate);
      return sessions.length ? sessions[sessions.length - 1].tracking_session_id
        : trackingSessionIdFor(symbol, sessionDate || chinaToday(), 1);
    }

    function maxOf(rows, key) {
      return rows.reduce((max, row) => Math.max(max, Number(row[key])), -Infinity);
    }

    function minOf(rows, key) {
      return rows.reduce((min, row) => Math.min(min, Number(row[key])), Infinity);
    }

    function nearestRuntimeWindowSample(buffer, current, windowSeconds) {
      const currentMs = runtimeSampleMilliseconds(current);
      if (!Number.isFinite(currentMs) || !Array.isArray(buffer) || buffer.length < 2
        || !current || current.data_status !== 'fresh') return null;
      const candidates = buffer.filter(sample => sample !== current && sample.data_status === 'fresh'
        && Number.isFinite(runtimeSampleMilliseconds(sample)));
      if (!candidates.length) return null;
      const targetMs = currentMs - windowSeconds * 1000;
      const nearest = candidates.reduce((best, sample) => {
        if (!best) return sample;
        return Math.abs(runtimeSampleMilliseconds(sample) - targetMs)
          < Math.abs(runtimeSampleMilliseconds(best) - targetMs) ? sample : best;
      }, null);
      const actualGap = nearest ? Math.abs(runtimeSampleMilliseconds(nearest) - targetMs) : Infinity;
      return actualGap <= RUNTIME_WINDOW_TOLERANCE_MS ? nearest : null;
    }

    function nextJsonpName() {
      jsonpCounter += 1;
      return `sinaData_${Date.now()}_${jsonpCounter}`;
    }

    function nextTrackerStartRequestedTime(now = new Date()) {
      // Compatibility field: it is now the current trading day's backfill anchor,
      // while started_at remains the actual Session creation audit timestamp.
      return TRACK_TIMES[0];
    }

    function nextTrackingSessionId(symbol, date, sessions, sequenceBySymbol = null) {
      const prefix = `TS-${String(date).replace(/-/g, '')}-${symbol}-`;
      const used = Object.keys(sessions || {}).map(key => String(key).startsWith(prefix)
        ? Number(String(key).slice(prefix.length)) || 0 : 0);
      const counterKey = `${date}|${symbol}`;
      const persisted = sequenceBySymbol && Number(sequenceBySymbol[counterKey]) || 0;
      const nextSequence = Math.max(persisted, 0, ...used) + 1;
      if (sequenceBySymbol) sequenceBySymbol[counterKey] = nextSequence;
      return trackingSessionIdFor(symbol, date, nextSequence);
    }

    function nodeForSymbol(symbol) {
      if (symbol.startsWith('sh')) return 'sh_a';
      if (symbol.startsWith('sz')) return 'sz_a';
      if (symbol.startsWith('bj')) return 'hs_bjs';
      throw new Error('暂不支持该市场。');
    }

    function normalizeAnalysisState(value) {
      const source = value && typeof value === 'object' ? value : {};
      const result = emptyAnalysisState();
      result.updated_at = source.updated_at || null;
      const provided = source.tracking_sessions && typeof source.tracking_sessions === 'object'
        ? source.tracking_sessions : {};
      Object.entries(provided).forEach(([trackingSessionId, cursor]) => {
        if (!cursor || typeof cursor !== 'object') return;
        result.tracking_sessions[trackingSessionId] = {
          tracking_session_id: trackingSessionId,
          symbol: String(cursor.symbol || ''),
          session_date: String(cursor.session_date || ''),
          last_processed_event_seq: Number(cursor.last_processed_event_seq ?? cursor.last_processed_seq) || 0,
          last_processed_event_id: cursor.last_processed_event_id || null,
          last_processed_observation_time: cursor.last_processed_observation_time || null,
          last_analyzed_at: cursor.last_analyzed_at || null,
          checkpoint_id: cursor.checkpoint_id || null,
          covered_handoff_id: cursor.covered_handoff_id || null
        };
      });
      if (source.symbols && typeof source.symbols === 'object') {
        Object.entries(source.symbols).forEach(([symbol, cursor]) => {
          if (!cursor || typeof cursor !== 'object') return;
          const trackingSessionId = legacyCursorTrackingSessionId(symbol, cursor.session_date || chinaToday());
          if (result.tracking_sessions[trackingSessionId]) return;
          result.tracking_sessions[trackingSessionId] = {
            tracking_session_id: trackingSessionId,
            symbol,
            session_date: cursor.session_date || chinaToday(),
            last_processed_event_seq: Number(cursor.last_processed_seq) || 0,
            last_processed_event_id: cursor.last_processed_event_id || null,
            last_processed_observation_time: cursor.last_processed_observation_time || null,
            last_analyzed_at: cursor.last_analyzed_at || null,
            checkpoint_id: cursor.checkpoint_id || null,
            covered_handoff_id: cursor.covered_handoff_id || null
          };
        });
      }
      return result;
    }

    function normalizeBars(data) {
      return data.map(item => {
        const parts = String(item.day || '').split(' ');
        return {
          date: parts[0],
          time: parts[1] || '15:00:00',
          open: Number(item.open),
          high: Number(item.high),
          low: Number(item.low),
          close: Number(item.close),
          volume: Number(item.volume || 0),
          amount: Number(item.amount || 0)
        };
      }).filter(item => item.date && Number.isFinite(item.close))
        .sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`));
    }

    function normalizeDecisionCheckpoint(value, analysisState = null) {
      const source = value && typeof value === 'object' ? value : {};
      const result = emptyDecisionCheckpoint();
      ['updated_at','analyzed_at','checkpoint_id','covered_handoff_id'].forEach(key => {
        result[key] = source[key] || null;
      });
      const provided = source.tracking_sessions && typeof source.tracking_sessions === 'object'
        ? source.tracking_sessions : {};
      Object.entries(provided).forEach(([trackingSessionId, decision]) => {
        if (!decision || typeof decision !== 'object') return;
        result.tracking_sessions[trackingSessionId] = { ...decision, tracking_session_id: trackingSessionId };
      });
      if (source.symbols && typeof source.symbols === 'object') {
        Object.entries(source.symbols).forEach(([symbol, decision]) => {
          if (!decision || typeof decision !== 'object') return;
          const matchingCursor = analysisState && analysisState.tracking_sessions
            ? Object.values(analysisState.tracking_sessions).find(cursor => cursor.symbol === symbol) : null;
          const trackingSessionId = decision.tracking_session_id
            || matchingCursor && matchingCursor.tracking_session_id
            || legacyCursorTrackingSessionId(symbol, chinaToday());
          if (!result.tracking_sessions[trackingSessionId]) {
            result.tracking_sessions[trackingSessionId] = { ...decision, symbol, tracking_session_id: trackingSessionId };
          }
        });
      }
      return result;
    }

    function normalizeSeverity(value) {
      const severity = String(value || '').toUpperCase();
      return Object.prototype.hasOwnProperty.call(EVENT_SEVERITY_ORDER, severity) ? severity : 'INFO';
    }

    function normalizeStockSymbol(value) {
      let raw = String(value || '').trim().toLowerCase().replace(/\s+/g, '');
      if (/^(sh|sz|bj)\d{6}$/.test(raw)) return raw;
      raw = raw.replace(/\D/g, '');
      if (!/^\d{6}$/.test(raw)) throw new Error('请输入6位股票代码，例如 920161 或 600519。');
      if (/^6/.test(raw)) return `sh${raw}`;
      if (/^[03]/.test(raw)) return `sz${raw}`;
      if (/^[489]/.test(raw)) return `bj${raw}`;
      throw new Error('无法自动识别市场，请在代码前加 sh、sz 或 bj。');
    }

    function normalizeTrackerStore(value) {
      const source = value && typeof value === 'object' ? value : {};
      const today = chinaToday();
      const rawSessions = source.sessions && typeof source.sessions === 'object' ? source.sessions : {};
      const sessions = {};
      const keyMap = new Map();
      const sequenceBySymbol = source.session_seq_by_symbol && typeof source.session_seq_by_symbol === 'object'
        ? { ...source.session_seq_by_symbol } : {};
      Object.entries(rawSessions).forEach(([oldKey, rawSession]) => {
        if (!rawSession || typeof rawSession !== 'object') return;
        const date = String(rawSession.date || String(oldKey).slice(0, 10) || today);
        const symbol = String(rawSession.symbol || String(oldKey).split('|')[1] || '');
        if (!symbol || date !== today) return;
        let trackingSessionId = String(rawSession.tracking_session_id || rawSession.trackingSessionId || '');
        if (!trackingSessionId || sessions[trackingSessionId]) {
          trackingSessionId = nextTrackingSessionId(symbol, date, sessions, sequenceBySymbol);
        } else {
          const sequence = Number(trackingSessionId.match(/-(\d+)$/)?.[1]) || 0;
          const counterKey = `${date}|${symbol}`;
          sequenceBySymbol[counterKey] = Math.max(Number(sequenceBySymbol[counterKey]) || 0, sequence);
        }
        const session = {
          ...rawSession,
          key: trackingSessionId,
          tracking_session_id: trackingSessionId,
          trackingSessionId,
          previous_tracking_session_id: rawSession.previous_tracking_session_id || null,
          lifecycle_status: normalizedTrackingStatus(rawSession.lifecycle_status),
          date,
          symbol,
          rows: Array.isArray(rawSession.rows) ? rawSession.rows : []
        };
        sessions[trackingSessionId] = session;
        keyMap.set(oldKey, trackingSessionId);
      });

      const normalizeItem = (rawItem, fallbackStatus) => {
        const symbol = String(rawItem && rawItem.symbol || '');
        const date = today;
        let trackingSessionId = String(rawItem && (rawItem.tracking_session_id || rawItem.trackingSessionId) || '');
        if (!trackingSessionId || !sessions[trackingSessionId] || sessions[trackingSessionId].date !== today) {
          const candidates = Object.values(sessions).filter(session => session.symbol === symbol && session.date === date)
            .sort((a, b) => String(a.createdAt || '').localeCompare(String(b.createdAt || '')));
          trackingSessionId = candidates.length ? candidates[candidates.length - 1].tracking_session_id : '';
        }
        const status = normalizedTrackingStatus(rawItem && rawItem.lifecycle_status || fallbackStatus);
        return {
          id: String(rawItem && rawItem.id || createId()),
          symbol,
          boardCode: String(rawItem && rawItem.boardCode || ''),
          csvEnabled: Boolean(rawItem && rawItem.csvEnabled),
          csvFileName: String(rawItem && rawItem.csvFileName || ''),
          lifecycle_status: status,
          aiSelected: typeof (rawItem && rawItem.aiSelected) === 'boolean'
            ? Boolean(rawItem.aiSelected) : status === TRACKING_STATUS.ACTIVE,
          tracking_session_id: trackingSessionId,
          previous_tracking_session_id: trackingSessionId ? rawItem && rawItem.previous_tracking_session_id || null : null,
          dropped_at: null
        };
      };

      let live = (Array.isArray(source.watchlist) ? source.watchlist : []).map(item => normalizeItem(item, TRACKING_STATUS.ACTIVE));
      live = live.filter(item => item.lifecycle_status !== TRACKING_STATUS.DROPPED).slice(0, MAX_TRACK_STOCKS);
      if (!Array.isArray(source.watchlist)) {
        const legacy = sessions[keyMap.get(source.activeKey)] || Object.values(sessions)[0];
        live = [normalizeItem({
          id: createId(), symbol: legacy && legacy.symbol ? legacy.symbol : 'bj920161',
          boardCode: legacy && legacy.selectedBoardCode ? legacy.selectedBoardCode : '',
          tracking_session_id: legacy && legacy.tracking_session_id || ''
        }, TRACKING_STATUS.ACTIVE)];
      }
      live.forEach(item => {
        if (item.symbol && !item.tracking_session_id) {
          item.tracking_session_id = nextTrackingSessionId(item.symbol, today, sessions, sequenceBySymbol);
          item.previous_tracking_session_id = null;
        }
        if (item.symbol && item.tracking_session_id && !sessions[item.tracking_session_id]) {
          const start = trackerSessionStartMetadata();
          sessions[item.tracking_session_id] = {
            key: item.tracking_session_id,
            tracking_session_id: item.tracking_session_id,
            trackingSessionId: item.tracking_session_id,
            previous_tracking_session_id: item.previous_tracking_session_id || null,
            lifecycle_status: item.lifecycle_status,
            date: today,
            symbol: item.symbol,
            stockName: '',
            selectedBoardCode: item.boardCode || '',
            started_at: start.started_at,
            start_requested_time: start.start_requested_time,
            createdAt: chinaNowText(),
            updatedAt: '',
            rows: []
          };
        }
        const session = sessions[item.tracking_session_id];
        if (session) session.lifecycle_status = item.lifecycle_status;
      });
      const referencedSessionIds = new Set(live.map(item => item.tracking_session_id).filter(Boolean));
      Object.keys(sessions).forEach(id => {
        if (!referencedSessionIds.has(id)) delete sessions[id];
      });
      const sourceActiveKey = keyMap.get(source.activeKey) || String(source.activeKey || '');
      return {
        schema_version: '2.1.1',
        runtime_date: today,
        activeKey: referencedSessionIds.has(sourceActiveKey) ? sourceActiveKey : '',
        sessions,
        watchlist: live,
        archivedWatchlist: [],
        session_seq_by_symbol: sequenceBySymbol,
        volumeRatioDays: Number(source.volumeRatioDays) === 10 ? 10 : 20
      };
    }

    function normalizedTrackingStatus(value) {
      const status = String(value || '').toUpperCase();
      return Object.prototype.hasOwnProperty.call(TRACKING_STATUS, status) ? status : TRACKING_STATUS.ACTIVE;
    }

    function normalizedTradeShares(rawVolume, amount, referencePrice, defaultLotSize = 1) {
      const raw = Number(rawVolume);
      if (!(raw >= 0)) return null;
      if (raw === 0) return 0;
      const money = Number(amount);
      const price = Number(referencePrice);
      if (!(money > 0) || !(price > 0)) return raw * defaultLotSize;
      const candidates = [raw, raw * 100];
      return candidates.reduce((best, shares) => {
        const score = Math.abs(Math.log((money / shares) / price));
        return !best || score < best.score ? { shares, score } : best;
      }, null).shares;
    }

    function numericMedian(values) {
      const nums = (values || []).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
      if (!nums.length) return null;
      const mid = Math.floor(nums.length / 2);
      return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
    }

    function openingMinuteBar(bars, date, point = '09:30') {
      const start = point === '13:00' ? '13:00' : '09:30';
      const end = point === '13:00' ? '13:02' : '09:32';
      return bars.find(row => {
        const time = row.time.slice(0, 5);
        return row.date === date && time >= start && time <= end;
      }) || null;
    }

    function preferredBoard(profile) {
      if (!profile) return null;
      return profile.industries.find(board => board.level === 2)
        || lastOf(profile.industries)
        || profile.concepts[0]
        || profile.regions[0]
        || null;
    }

    function previousDailyClose(dailyBars, date) {
      const candidates = dailyBars.filter(row => row.date < date);
      return candidates.length ? lastOf(candidates).close : null;
    }

    function pushRuntimeSample(symbol, sample) {
      const stockState = ensureRuntimeStockState(symbol);
      stockState.buffer.push(sample);
      if (stockState.buffer.length > RUNTIME_BUFFER_MAX) {
        stockState.buffer.splice(0, stockState.buffer.length - RUNTIME_BUFFER_MAX);
      }
      Object.assign(sample, computeRuntimeWindowFields(stockState.buffer, sample));
      stockState.latest = sample;
      return sample;
    }

    function rebuildEventRuntimeKeys() {
      eventEngine.eventKeys = new Set(eventEngine.events.map(event => event.event_key || eventKeyFromEvent(event)).filter(Boolean));
      eventEngine.persistedEventKeys = new Set([...eventEngine.persistedEventKeys]
        .filter(key => eventEngine.eventKeys.has(key)));
    }

    function rowsWithEventDetails(rows) {
      return (Array.isArray(rows) ? rows : []).map(row => ({ ...row, eventDetails: eventDetailsForRow(row) }));
    }

    function runtimeCacheEnvelope(entry, dataStatus, now = Date.now()) {
      return {
        value: entry.value,
        data_status: dataStatus,
        source_updated_at: entry.updated_at ? chinaIsoText(new Date(entry.updated_at)) : null,
        data_age_ms: entry.updated_at ? Math.max(0, now - entry.updated_at) : null
      };
    }

    function runtimeCacheHasValue(entry) {
      return Boolean(entry && Object.prototype.hasOwnProperty.call(entry, 'value')
        && typeof entry.value !== 'undefined');
    }

    async function runtimeCachedFetch(bucket, key, ttlMs, fetcher) {
      const now = Date.now();
      const existing = bucket.get(key);
      if (runtimeCacheHasValue(existing) && now - existing.updated_at < ttlMs) {
        return runtimeCacheEnvelope(existing, 'fresh', now);
      }
      if (existing && existing.promise) return existing.promise;

      const entry = {
        value: runtimeCacheHasValue(existing) ? existing.value : undefined,
        updated_at: existing && existing.updated_at ? existing.updated_at : 0,
        promise: null,
        last_error: existing && existing.last_error ? existing.last_error : ''
      };
      entry.promise = (async () => {
        try {
          const value = await fetcher();
          entry.value = value;
          entry.updated_at = Date.now();
          entry.last_error = '';
          entry.last_status = 'fresh';
          return runtimeCacheEnvelope(entry, 'fresh');
        } catch (error) {
          entry.last_error = error.message || String(error);
          entry.last_status = 'stale';
          if (runtimeCacheHasValue(existing)) return runtimeCacheEnvelope(entry, 'stale');
          throw error;
        } finally {
          entry.promise = null;
        }
      })();
      bucket.set(key, entry);
      return entry.promise;
    }

    function runtimeConfiguredItems() {
      return tracker.store.watchlist.filter(item => /^(sh|sz|bj)\d{6}$/.test(String(item.symbol || '')));
    }

    function runtimeDataAgeMs(sourceTimestamp, nowDate = runtimeNow()) {
      const parsed = Date.parse(runtimeSourceTimestampText(sourceTimestamp, nowDate));
      return Number.isFinite(parsed) ? Math.max(0, nowDate.getTime() - parsed) : null;
    }

    function runtimeFieldDelta(current, previous, key) {
      return current && previous && hasNumber(current[key]) && hasNumber(previous[key])
        ? Number(current[key]) - Number(previous[key]) : null;
    }

    function runtimeNow() {
      const supplied = runtimeMonitor.testNowProvider ? runtimeMonitor.testNowProvider() : new Date();
      const date = supplied instanceof Date ? supplied : new Date(supplied);
      return Number.isFinite(date.getTime()) ? date : new Date();
    }

    function runtimeSampleMilliseconds(sample) {
      const value = Date.parse(sample && sample.timestamp);
      return Number.isFinite(value) ? value : null;
    }

    function runtimeSourceTimestampText(value, fallbackDate = runtimeNow()) {
      if (hasNumber(value) && Number(value) > 100000000000) return chinaIsoText(new Date(Number(value)));
      const text = String(value || '').trim();
      if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/.test(text)) return text;
      if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text)) return `${text.replace(' ', 'T')}+08:00`;
      const parsed = Date.parse(text);
      return Number.isFinite(parsed) ? chinaIsoText(new Date(parsed)) : chinaIsoText(fallbackDate);
    }

    function runtimeStateStockPayload(sample, bufferSize) {
      const keys = [
        'name','data_status','source_updated_at','data_age_ms','trade_source','trade_source_captured_at','trade_data_age_ms',
        'price','open','high','low','cumulative_volume','cumulative_amount','cumulative_turnover',
        'vwap','price_vwap_pct','stock_pct','industry_pct','alpha','industry_breadth',
        'sh_pct','cyb_pct','bse_pct','star_pct','delta_price_15s','delta_price_30s','delta_price_60s',
        'delta_volume_30s','delta_volume_60s','delta_amount_30s','delta_amount_60s',
        'delta_turnover_30s','delta_turnover_60s','alpha_change_30s','alpha_change_60s','price_efficiency_60s'
      ];
      return {
        timestamp: sample.timestamp,
        ...Object.fromEntries(keys.map(key => [key, hasNumber(sample[key]) ? Number(sample[key]) : sample[key] ?? null])),
        data_age_ms: runtimeDataAgeMs(sample.source_updated_at),
        trade_data_age_ms: runtimeDataAgeMs(sample.trade_source_captured_at),
        buffer_size: bufferSize
      };
    }

    function runtimeTradingSessionInfo(date = runtimeNow()) {
      const now = date instanceof Date ? date : new Date(date);
      const p = chinaDateParts(now);
      const time = `${p.hour}:${p.minute}:${p.second}`;
      const weekday = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Shanghai', weekday: 'short'
      }).format(now);
      if (weekday === 'Sat' || weekday === 'Sun') return { active: false, label: '当前休市', time };
      if ((time >= '09:30:00' && time <= '11:30:00') || (time >= '13:00:00' && time <= '15:00:00')) {
        return { active: true, label: '', time };
      }
      return { active: false, label: time > '15:00:00' ? '已收盘' : '当前休市', time };
    }

    function samePeriodVolumeStats(historyBars, currentDate, start, end, currentVolume, lookbackDays) {
      if (!hasNumber(currentVolume) || Number(currentVolume) < 0 || !isFiveMinuteBoundary(start)
        || !isFiveMinuteBoundary(end) || end <= start || end === '09:30') return null;
      const byDate = new Map();
      historyBars.forEach(bar => {
        if (bar.date >= currentDate) return;
        const time = bar.time.slice(0, 5);
        if (time <= start || time > end) return;
        byDate.set(bar.date, (byDate.get(bar.date) || 0) + (Number(bar.volume) || 0));
      });
      const samples = Array.from(byDate.entries())
        .sort((a, b) => b[0].localeCompare(a[0]))
        .slice(0, lookbackDays)
        .map(item => item[1])
        .filter(value => value > 0);
      if (!samples.length) return null;
      const average = samples.reduce((sum, value) => sum + value, 0) / samples.length;
      if (!(average > 0)) return null;
      return { ratio: Number(currentVolume) / average, sample: samples.length, average };
    }

    async function sampleOneRuntimeStock(item, generation, indexSnapshot) {
      const stockState = ensureRuntimeStockState(item.symbol);
      if (stockState.inFlight) return null;
      stockState.inFlight = true;
      try {
        const fields = runtimeMonitor.testSampleProvider
          ? await runtimeMonitor.testSampleProvider(item, stockState.latest || {})
          : await collectRuntimeStockFields(item, indexSnapshot);
        const sampledAt = runtimeNow();
        if (!runtimeMonitor.running || generation !== runtimeMonitor.generation
          || !isRuntimeTradingSession(sampledAt)) return null;
        const sample = {
          ...fields,
          timestamp: fields.timestamp || chinaIsoText(sampledAt),
          symbol: item.symbol
        };
        sample.data_status = fields.data_status === 'stale' ? 'stale' : 'fresh';
        sample.source_updated_at = runtimeSourceTimestampText(fields.source_updated_at || sample.timestamp, sampledAt);
        sample.data_age_ms = hasNumber(fields.data_age_ms)
          ? Math.max(0, Number(fields.data_age_ms)) : runtimeDataAgeMs(sample.source_updated_at, sampledAt);
        sample.trade_source = String(fields.trade_source || '');
        sample.trade_source_captured_at = runtimeSourceTimestampText(
          fields.trade_source_captured_at || sample.source_updated_at, sampledAt
        );
        sample.trade_data_age_ms = hasNumber(fields.trade_data_age_ms)
          ? Math.max(0, Number(fields.trade_data_age_ms))
          : runtimeDataAgeMs(sample.trade_source_captured_at, sampledAt);
        return pushRuntimeSample(item.symbol, sample);
      } finally {
        stockState.inFlight = false;
      }
    }

    function setTrackerLifecycle(id, nextStatus) {
      if (tracker.busy) return false;
      const item = getWatchItem(id);
      if (!item) return false;
      const status = normalizedTrackingStatus(nextStatus);
      if (status === TRACKING_STATUS.DROPPED) return dropTrackerStock(id);
      item.lifecycle_status = status;
      if (status === TRACKING_STATUS.PAUSED) item.aiSelected = false;
      if (status === TRACKING_STATUS.ACTIVE) item.aiSelected = true;
      const session = trackerSessionForItem(item);
      if (session) session.lifecycle_status = status;
      saveTrackerStore();
      renderTracker();
      showToast(status === TRACKING_STATUS.ACTIVE
        ? `${session && session.stockName || item.symbol} 已恢复观察。`
        : `${session && session.stockName || item.symbol} 已暂停重点观察；5分钟采集继续，默认不进入Handoff。`);
      return true;
    }

    function sinaCumulativeTradeMetrics(priceRows, symbol) {
      // This is the compatibility path used especially for Beijing Stock Exchange symbols.
      // The older BSE-working version already proved Sina's minute K-line OHLC/volume/amount
      // is available when Eastmoney stock-level trade endpoints occasionally return no usable data.
      const rows = Array.isArray(priceRows) ? priceRows : [];
      if (!rows.length) return null;

      const low = minOf(rows, 'low');
      const high = maxOf(rows, 'high');
      const tolerance = Math.max(.02, Math.abs(high) * .0015);
      let amount = 0;
      let volume = 0;
      let hasAmount = false;
      let hasVolume = false;
      let amountSeriesComplete = true;
      let amountSeriesIssue = '';

      rows.forEach(row => {
        const rawVolume = Number(row.volume);
        const rowAmount = Number(row.amount);
        const referencePrice = Number(row.close || row.open);
        const barLow = Number(row.low || row.close || row.open);
        const barHigh = Number(row.high || row.close || row.open);
        if (rawVolume > 0) {
          // Volume is useful on BSE even when amount is missing. Preserve it for turnover/ratio.
          const shares = rowAmount > 0 && referencePrice > 0
            ? normalizedTradeShares(rawVolume, rowAmount, referencePrice, 1)
            : rawVolume;
          if (shares > 0) {
            volume += shares;
            hasVolume = true;

            // For historical VWAP/amount, EVERY positive-volume minute must carry a valid amount.
            // Otherwise a later minute can make the cumulative average look plausible again even
            // though an earlier amount is still missing, causing the false "VWAP reappears" bug.
            if (!(rowAmount > 0)) {
              amountSeriesComplete = false;
              amountSeriesIssue = '新浪分钟成交额存在缺口；该缺口后的历史累计成交额/VWAP均不再回填';
            } else {
              const implied = rowAmount / shares;
              const barTolerance = Math.max(.02, Math.abs(barHigh) * .0015);
              if (!Number.isFinite(implied) || implied < barLow - barTolerance || implied > barHigh + barTolerance) {
                amountSeriesComplete = false;
                amountSeriesIssue = '新浪分钟成交额与成交量逐分钟口径不一致；历史累计成交额/VWAP留空';
              }
            }
          }
        }
        if (rowAmount > 0) {
          amount += rowAmount;
          hasAmount = true;
        }
      });

      if (!hasVolume && !hasAmount) return null;
      let vwap = hasVolume && hasAmount && volume > 0 && amount > 0 ? amount / volume : null;
      let issue = '';
      let amountTrusted = Boolean(amountSeriesComplete && hasAmount && hasVolume && volume > 0 && amount > 0);
      if (!amountSeriesComplete) {
        // Preserve source arithmetic. Validation is advisory only: raw amount, Δamount and VWAP
        // continue to be calculated, while the row is marked pending verification.
        amountTrusted = false;
        issue = amountSeriesIssue || '新浪分钟量额口径待校验；原始成交额与VWAP仍按原始量额计算';
      } else if (hasVolume && hasAmount && volume > 0 && amount > 0) {
        const candidate = amount / volume;
        if (!Number.isFinite(candidate) || candidate < low - tolerance || candidate > high + tolerance) {
          amountTrusted = false;
          issue = '新浪分钟量额隐含均价超出累计价格区间；原始成交额与VWAP保留，状态标记为待校验';
        }
      } else {
        amountTrusted = false;
        vwap = null;
        issue = hasVolume
          ? '新浪分钟成交量可用，但成交额缺失；无法计算VWAP'
          : '新浪分钟成交额可见，但成交量缺失；无法计算VWAP';
      }

      return {
        volume: hasVolume ? volume : null,
        amount: hasAmount ? amount : null,
        amountTrusted,
        vwap, low, high, issue,
        source: isBeijingSymbol(symbol)
          ? '新浪分钟成交（北交所原链路保留）'
          : '新浪分钟成交（兼容路径）'
      };
    }

    function sumOf(rows, key) {
      return rows.reduce((sum, row) => sum + (Number(row[key]) || 0), 0);
    }

    function syncTrackerEventsToLedger() {
      const sessionDate = eventToday();
      const created = [];
      tracker.store.watchlist.forEach(item => {
        const session = trackerSessionForItem(item);
        if (!session || session.date !== sessionDate || !Array.isArray(session.rows) || !session.rows.length) return;
        trackerRowsWithEventDetails(session.rows).forEach(row => {
          eventDetailsForRow(row).forEach(detail => {
            const key = `${session.tracking_session_id}|${row.requestedTime}|${detail.type}`;
            if (!eventEngine.eventKeys.has(key)) created.push(createTrackerLedgerEvent(session, row, detail));
          });
        });
      });
      if (created.length) saveEventEngineStore();
      return created;
    }

    function timeToSeconds(time) {
      const [hour, minute, second = '0'] = String(time).split(':');
      return Number(hour) * 3600 + Number(minute) * 60 + Number(second);
    }

    function trackerComparisonPrevious(rows, requestedTime, position = rows.length) {
      const candidates = rows.slice(0, position);
      const earlierRows = (TRACK_TIMES.includes(requestedTime) ? formalTrackerRows(candidates) : candidates)
        .filter(row => String(row.requestedTime || '') < String(requestedTime || ''));
      return lastOf(earlierRows);
    }

    function trackerDeltaRows(rows) {
      let runningLow = Infinity;
      let runningHigh = -Infinity;
      const derived = rows.map((row, index) => {
        const previous = trackerComparisonPrevious(rows, row.requestedTime, index);
        runningLow = Math.min(runningLow, hasNumber(row.low) ? Number(row.low) : Infinity);
        runningHigh = Math.max(runningHigh, hasNumber(row.high) ? Number(row.high) : -Infinity);

        const deltaVolume = previous ? deltaValue(row.cumulativeVolume, previous.cumulativeVolume) : null;
        const deltaAmount = previous ? deltaValue(row.amount, previous.amount) : null;
        const deltaTurnover = previous ? deltaValue(row.turnover, previous.turnover) : null;
        const intervalChange = previous && hasNumber(previous.price) && Number(previous.price) > 0 && hasNumber(row.price)
          ? (Number(row.price) / Number(previous.price) - 1) * 100 : null;
        const priceEfficiency = hasNumber(intervalChange) && hasNumber(deltaTurnover) && Math.abs(Number(deltaTurnover)) >= 0.01
          ? Number(intervalChange) / Number(deltaTurnover) : null;

        let cumulativeVwap = hasNumber(row.vwap) ? Number(row.vwap)
          : hasNumber(row.amount) && Number(row.amount) > 0 && hasNumber(row.cumulativeVolume) && Number(row.cumulativeVolume) > 0
            ? Number(row.amount) / Number(row.cumulativeVolume) : null;
        const tolerance = hasNumber(row.price) ? Math.max(.02, Math.abs(Number(row.price)) * .0015) : .02;
        const vwapGap = hasNumber(cumulativeVwap) && Number(cumulativeVwap) > 0 && hasNumber(row.price)
          ? (Number(row.price) / Number(cumulativeVwap) - 1) * 100 : null;

        let intervalVwap = hasNumber(deltaAmount) && Number(deltaAmount) > 0 && hasNumber(deltaVolume) && Number(deltaVolume) > 0
          ? Number(deltaAmount) / Number(deltaVolume) : null;
        const intervalLow = hasNumber(row.low) ? Number(row.low) : null;
        const intervalHigh = hasNumber(row.high) ? Number(row.high) : null;

        return {
          ...row,
          vwap: cumulativeVwap,
          vwapGap,
          comparisonTime: previous ? previous.requestedTime : '',
          deltaVolume,
          deltaTurnover,
          deltaAmount,
          intervalVwap,
          intervalChange,
          priceEfficiency,
          eventTags: []
        };
      });

      derived.forEach((row, index) => {
        if (row.auctionPoint) return;
        const priorRows = derived.slice(0, index);
        const eventRows = TRACK_TIMES.includes(row.requestedTime) ? formalTrackerRows(priorRows) : priorRows;
        const previous = lastOf(eventRows);
        const earlier = eventRows.filter(item => !item.auctionPoint);
        const priorLow = earlier.length ? Math.min(...earlier.map(item => Number(item.low)).filter(Number.isFinite)) : null;
        const priorHigh = earlier.length ? Math.max(...earlier.map(item => Number(item.high)).filter(Number.isFinite)) : null;
        const tags = [];
        const pxTol = hasNumber(row.price) ? Math.max(.02, Math.abs(Number(row.price)) * .0015) : .02;
        const newLow = hasNumber(priorLow) && hasNumber(row.low) && Number(row.low) < Number(priorLow) - pxTol;
        const newHigh = hasNumber(priorHigh) && hasNumber(row.high) && Number(row.high) > Number(priorHigh) + pxTol;
        if (newLow) tags.push('新低');
        if (newHigh) tags.push('新高');
        if (newLow && hasNumber(row.volumeRatio) && Number(row.volumeRatio) >= 1.5 && hasNumber(row.intervalChange) && Number(row.intervalChange) < 0) {
          tags.push('放量破位');
        }
        if (!newLow && hasNumber(row.intervalChange) && Number(row.intervalChange) < 0
          && hasNumber(row.volumeRatio) && Number(row.volumeRatio) <= 0.8) {
          tags.push('缩量回踩');
        }
        if (previous && row.amountTrusted !== false && previous.amountTrusted !== false
          && hasNumber(previous.vwapGap) && Number(previous.vwapGap) <= 0
          && hasNumber(row.vwapGap) && Number(row.vwapGap) > 0) {
          tags.push('VWAP重新夺回');
        }
        if (previous && hasNumber(row.alpha) && hasNumber(previous.alpha)
          && Number(row.alpha) - Number(previous.alpha) <= -0.8) {
          tags.push('Alpha快速恶化');
        }
        if (hasNumber(priorLow) && hasNumber(row.low) && !newLow && earlier.length >= 3
          && Math.abs(Number(row.low) / Number(priorLow) - 1) <= 0.0035) {
          tags.push('支撑二次测试');
        }
        if (previous && hasNumber(row.priceEfficiency) && hasNumber(previous.priceEfficiency)
          && Math.sign(Number(row.priceEfficiency)) === Math.sign(Number(previous.priceEfficiency))
          && Math.abs(Number(previous.priceEfficiency)) >= 0.05
          && Math.abs(Number(row.priceEfficiency)) <= Math.abs(Number(previous.priceEfficiency)) * 0.5
          && hasNumber(row.deltaTurnover) && Number(row.deltaTurnover) >= 0.15) {
          tags.push('价格效率衰减');
        }
        row.eventTags = Array.from(new Set(tags));
      });
      return derived;
    }

    function trackerDueTimes(session) {
      if (!session || session.date !== chinaToday()) return [];
      const nowSeconds = timeToSeconds(chinaTimeText(true));
      const captured = new Set(session.rows
        .filter(row => row.scheduleTime || TRACK_TIMES.includes(row.requestedTime))
        .map(row => row.scheduleTime || row.requestedTime));
      return TRACK_TIMES.filter(time => nowSeconds >= timeToSeconds(time) + trackerGraceSeconds(time)
        && !captured.has(time));
    }

    function trackerEventDetectedAt(row) {
      const captured = String(row && row.capturedAt || '').trim();
      if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(captured)) return `${captured.replace(' ', 'T')}+08:00`;
      if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$/.test(captured)) return captured;
      if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(captured)) return `${captured}+08:00`;
      return eventIsoText();
    }

    function trackerEventEvidence(row) {
      const keys = [
        'open','high','low','price','cumulativeVolume','deltaVolume','amount','deltaAmount','turnover','deltaTurnover',
        'vwap','intervalVwap','stockChange','boardChange','alpha','volumeRatio','vwapGap','intervalChange',
        'priceEfficiency','boardMedianChange'
      ];
      return Object.fromEntries(keys.map(key => [key, hasNumber(row[key]) ? Number(row[key]) : null]));
    }

    function trackerEventTimestamp(session, row) {
      const requested = /^\d{2}:\d{2}$/.test(String(row.requestedTime || '')) ? row.requestedTime : '00:00';
      return `${session.date}T${requested}:00+08:00`;
    }

    function trackerGraceSeconds(time) {
      if (time === '09:25') return 8;
      return time === '09:30' ? 90 : 35;
    }

    function trackerIntervalStart(previous, requestedTime) {
      if (requestedTime === '09:25') return '09:15';
      let start = previous && previous.requestedTime ? previous.requestedTime : '09:30';
      if (requestedTime >= '13:00' && start <= '11:30') start = '13:00';
      if (!start || start > requestedTime) start = requestedTime >= '13:00' ? '13:00' : '09:30';
      return start;
    }

    function trackerRowsWithEventDetails(rows) {
      return rowsWithEventDetails(trackerDeltaRows(rows));
    }

    function trackerSessionForItem(item) {
      const session = item && item.tracking_session_id ? tracker.store.sessions[item.tracking_session_id] || null : null;
      return session && session.date === chinaToday() ? session : null;
    }

    function trackerSessionStartMetadata(now = new Date()) {
      return {
        started_at: chinaIsoText(now),
        start_requested_time: nextTrackerStartRequestedTime(now)
      };
    }

    function trackingSessionIdFor(symbol, date, sequence) {
      return `TS-${String(date).replace(/-/g, '')}-${symbol}-${String(sequence).padStart(2, '0')}`;
    }

    function trackingSessionSequenceFor(trackingSessionId, symbol, date) {
      const prefix = `TS-${String(date).replace(/-/g, '')}-${symbol}-`;
      const text = String(trackingSessionId || '');
      if (!text.startsWith(prefix)) return 0;
      const suffix = text.slice(prefix.length);
      return /^\d+$/.test(suffix) && Number(suffix) > 0 ? Number(suffix) : 0;
    }

    function trackingSessionsForSymbol(symbol, date = chinaToday()) {
      return Object.values(tracker.store.sessions).filter(session => session.symbol === symbol && session.date === date)
        .sort((a, b) => String(a.createdAt || '').localeCompare(String(b.createdAt || '')));
    }

    function validTradeBar(bar) {
      const volume = Number(bar && bar.volume);
      const amount = Number(bar && bar.amount);
      if (!(volume > 0)) return volume === 0;
      if (!(amount > 0)) return false;
      const average = amount / volume;
      const low = Number(bar.low || bar.close);
      const high = Number(bar.high || bar.close);
      const tolerance = Math.max(.02, Math.abs(high) * .0015);
      return average >= low - tolerance && average <= high + tolerance;
    }

    function validatedCumulativeTradeMetrics(tradeBars, priceBars) {
      const rows = Array.isArray(tradeBars) ? tradeBars : [];
      if (!rows.length || rows.some(row => !validTradeBar(row))) return null;
      const volume = sumOf(rows, 'volume');
      const amount = sumOf(rows, 'amount');
      if (!(volume > 0) || !(amount > 0)) return null;
      const prices = Array.isArray(priceBars) && priceBars.length ? priceBars : rows;
      const low = minOf(prices, 'low');
      const high = maxOf(prices, 'high');
      const vwap = amount / volume;
      const tolerance = Math.max(.02, Math.abs(high) * .0015);
      if (!Number.isFinite(vwap) || vwap < low - tolerance || vwap > high + tolerance) return null;
      return { volume, amount, amountTrusted: true, vwap, low, high };
    }

async function getTrackerDataset(...args) { const recorded=ports.recordedDataset?.(...args); return recorded || fetchTrackerDatasetNative(...args); }

  return {assignTrackingSessionToItem,backfillTrackerBoardChanges,backfillTrackerMetrics,barsInTradingInterval,boardChangeAt,boardRetryDelay,breadthForRequestedTime,breadthRetryDelay,buildAuctionTrackerRow,buildFiveMinuteTrackTimes,buildRuntimeStateDocument,buildTrackerRow,cachedBoardMinuteData,canRetryBreadthRow,captureOneTracker,chinaDateParts,chinaIsoText,chinaNowText,chinaTimeText,chinaToday,collectRuntimeStockFields,computeRuntimeWindowFields,configuredTrackerSessions,createId,createTrackerLedgerEvent,cumulativeSnapshotForRequestedTime,cumulativeTradeMetricsForTime,currentTrackerPoint,deltaValue,dropTrackerStock,eastmoneyMarketData,eastmoneyStockSecid,emptyAnalysisState,emptyDecisionCheckpoint,ensureAllTrackingSessionCursors,ensureAnalysisCursorForSession,ensureRuntimeStockState,ensureTrackerBoardProfile,ensureTrackerSession,eventActionability,eventDefinition,eventDetailsForRow,eventIdFor,eventIsoText,eventKeyFromEvent,eventNow,eventSequenceMax,eventToday,fetchBoardBreadthConstituents,findCurrentQuote,firstRuntimeNumber,firstRuntimePositive,firstSuccessful,formalTrackerRows,getBoardBreadth,getBoardByCode,getBoardHealth,getBoardMinuteData,getBreadthHealth,getCumulativeStockSnapshot,getEastmoneyCumulativeSnapshot,getKline,getMarketData,getRuntimeBoardProfile,getRuntimeBreadthSnapshot,getRuntimeIndexSnapshot,getRuntimeIndustrySnapshot,getRuntimeProfile,getRuntimeStockBundle,getSharedTrackerMarketData,getSinaCumulativeSnapshot,getStockBoards,getStockProfile,getStockTradeMinuteData,getVolumeHistory,getWatchItem,handoffContainsTrackingSession,handoffTrackingSessionIds,hasNumber,indexChangeAt,invalidateDeletedTrackingSession,isBeijingSymbol,isFiveMinuteBoundary,isRuntimeTradingSession,lastOf,legacyCursorTrackingSessionId,maxOf,minOf,nearestRuntimeWindowSample,nextJsonpName,nextTrackerStartRequestedTime,nextTrackingSessionId,nodeForSymbol,normalizeAnalysisState,normalizeBars,normalizeDecisionCheckpoint,normalizeSeverity,normalizeStockSymbol,normalizeTrackerStore,normalizedTrackingStatus,normalizedTradeShares,numericMedian,openingMinuteBar,preferredBoard,previousDailyClose,pushRuntimeSample,rebuildEventRuntimeKeys,rowsWithEventDetails,runtimeCacheEnvelope,runtimeCacheHasValue,runtimeCachedFetch,runtimeConfiguredItems,runtimeDataAgeMs,runtimeFieldDelta,runtimeNow,runtimeSampleMilliseconds,runtimeSourceTimestampText,runtimeStateStockPayload,runtimeTradingSessionInfo,samePeriodVolumeStats,sampleOneRuntimeStock,setTrackerLifecycle,sinaCumulativeTradeMetrics,sumOf,syncTrackerEventsToLedger,timeToSeconds,trackerComparisonPrevious,trackerDeltaRows,trackerDueTimes,trackerEventDetectedAt,trackerEventEvidence,trackerEventTimestamp,trackerGraceSeconds,trackerIntervalStart,trackerRowsWithEventDetails,trackerSessionForItem,trackerSessionStartMetadata,trackingSessionIdFor,trackingSessionSequenceFor,trackingSessionsForSymbol,validTradeBar,validatedCumulativeTradeMetrics,getTrackerDataset,TRACK_TIMES,EVENT_DEFINITIONS,RUNTIME_CACHE_TTL,INDEXES};
}
