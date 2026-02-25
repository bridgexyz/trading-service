export interface TradingPair {
  id: number;
  name: string;
  asset_a: string;
  asset_b: string;
  lighter_market_a: number;
  lighter_market_b: number;
  entry_z: number;
  exit_z: number;
  stop_z: number;
  window_interval: string;
  window_candles: number;
  train_interval: string;
  train_candles: number;
  max_half_life: number;
  rsi_upper: number;
  rsi_lower: number;
  rsi_period: number;
  stop_loss_pct: number;
  position_size_pct: number;
  leverage: number;
  twap_minutes: number;
  min_equity_pct: number;
  schedule_interval: string;
  is_enabled: boolean;
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
  account_index: number;
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
