export interface TradingPair {
  id: number;
  name: string;
  asset_a: string;
  asset_b: string;
  lighter_market_a: number;
  lighter_market_b: number;
  entry_z: number;
  exit_z_early: number;
  exit_z_late: number;
  stop_z: number;
  window_interval: string;
  window_candles: number;
  train_interval: string;
  train_candles: number;
  max_half_life: number;
  rsi_upper: number;
  rsi_lower: number;
  rsi_period: number;
  rsi_a_lower: number;
  rsi_a_upper: number;
  rsi_b_lower: number;
  rsi_b_upper: number;
  stop_loss_pct: number;
  position_size_pct: number;
  leverage: number;
  order_mode: string;
  slice_chunks: number;
  slice_delay_sec: number;
  min_equity_pct: number;
  cooldown_losses: number;
  cooldown_loss_pct: number;
  cooldown_drawdown_pct: number;
  cooldown_candles: number;
  schedule_interval: string;
  exit_schedule_interval: string;
  use_exit_schedule: boolean;
  is_enabled: boolean;
  guardian_excluded: boolean;
  credential_id: number | null;
  current_equity: number;
  created_at: string;
  updated_at: string;
}

export interface Trade {
  id: number;
  pair_id: number;
  direction: string;
  entry_time: string;
  exit_time: string;
  entry_price_a: number;
  exit_price_a: number;
  entry_price_b: number;
  exit_price_b: number;
  size_a: number;
  size_b: number;
  hedge_ratio: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
  duration_candles: number;
}

export interface Credential {
  id: number;
  name: string;
  lighter_host: string;
  api_key_index: number;
  account_index: string;
  is_active: boolean;
  created_at: string;
}

export interface JobLog {
  id: number;
  pair_id: number;
  timestamp: string;
  status: string;
  z_score: number | null;
  hedge_ratio: number | null;
  half_life: number | null;
  rsi: number | null;
  close_a: number | null;
  close_b: number | null;
  action: string | null;
  message: string | null;
  market_data: Record<string, { count: number; first: string | null; last: string | null }> | null;
}

export interface DashboardSummary {
  total_pairs: number;
  active_pairs: number;
  open_positions: number;
  total_trades: number;
  total_pnl: number;
  win_rate: number;
}

export interface SchedulerJob {
  id: string;
  name: string;
  next_run: string | null;
  trigger: string;
}

export interface SchedulerStatus {
  running: boolean;
  job_count: number;
  jobs: SchedulerJob[];
}

export interface EnrichedPosition {
  id: number;
  pair_id: number;
  pair_name: string;
  direction: number;
  entry_z: number;
  entry_price_a: number;
  entry_price_b: number;
  current_price_a: number;
  current_price_b: number;
  entry_notional: number;
  entry_time: string;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

export interface ExchangePosition {
  market_index: number;
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  current_price: number;
  notional: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

export interface SimplePairTrade {
  id: number;
  asset_a: string;
  asset_b: string;
  lighter_market_a: number;
  lighter_market_b: number;
  direction: number;
  ratio: number;
  margin_usd: number;
  leverage: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  slice_chunks: number;
  slice_delay_sec: number;
  credential_id: number | null;
  status: string;
  entry_price_a: number | null;
  entry_price_b: number | null;
  fill_size_a: number | null;
  fill_size_b: number | null;
  entry_notional: number | null;
  entry_time: string | null;
  exit_price_a: number | null;
  exit_price_b: number | null;
  exit_time: string | null;
  exit_reason: string | null;
  pnl: number | null;
  pnl_pct: number | null;
  created_at: string;
}

export interface LoginRequest {
  username: string;
  password: string;
  totp_code: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface EmergencyStopRequest {
  close_positions: boolean;
  disable_pairs: boolean;
}

export interface EmergencyStopResponse {
  positions_closed: number;
  errors: string[];
  pairs_disabled: number;
}

export interface GuardianSettings {
  id: number;
  enabled: boolean;
  interval_minutes: number;
  stop_loss_pct_override: number | null;
  updated_at: string;
}

export interface GuardianStatus {
  enabled: boolean;
  interval_minutes: number;
  job_running: boolean;
  next_run: string | null;
  trigger: string | null;
  monitored_positions: number;
}
