"""
Main backtesting engine for options strategies.

Orchestrates the simulation of trading strategies over historical data.
Handles position management, signal processing, and result persistence.
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import (
    BacktestRun, SimulatedTrade, DailyEquityCurve, 
    ExitReason, RegimeLabel, Session as DbSession,
    DailyBrief, EnsembleDecision
)
from app.backtest.config import BacktestConfig, SimulatedPositionState
from app.backtest.data_provider import DataProvider, OptionQuote
from app.backtest.metrics import PerformanceCalculator

logger = logging.getLogger(__name__)


class OptionsBacktester:
    """
    Core engine for running options backtests.
    
    Simulates trading day-by-day, managing positions and tracking performance.
    """
    
    def __init__(
        self,
        config: BacktestConfig,
        data_provider: DataProvider,
        db_session: Session
    ):
        self.config = config
        self.data_provider = data_provider
        self.db = db_session
        
        # State
        self.current_date: date = config.start_date
        self.cash: Decimal = Decimal(str(config.initial_capital))
        self.equity: Decimal = Decimal(str(config.initial_capital))
        self.positions: List[SimulatedPositionState] = []
        self.closed_trades: List[SimulatedTrade] = []
        self.equity_curve: List[DailyEquityCurve] = []
        self.run_id: Optional[uuid.UUID] = None
        
        # Performance tracking
        self.high_water_mark: Decimal = Decimal(str(config.initial_capital))
        self.drawdown: Decimal = Decimal("0")
        
    def run(self) -> BacktestRun:
        """
        Execute the full backtest simulation.
        
        Returns:
            BacktestRun object with results
        """
        logger.info(f"Starting backtest from {self.config.start_date} to {self.config.end_date}")
        
        # Create run record
        run_record = BacktestRun(
            strategy_version=self.config.strategy_version,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_capital=self.config.initial_capital,
            parameters=self.config.to_dict(),
            status="RUNNING"
        )
        self.db.add(run_record)
        self.db.commit()
        self.db.refresh(run_record)
        self.run_id = run_record.run_id
        
        try:
            # Main simulation loop
            current = self.config.start_date
            while current <= self.config.end_date:
                # Skip weekends
                if current.weekday() < 5:
                    self.current_date = current
                    self._process_day(current)
                
                current += timedelta(days=1)
                
            # Close any remaining open positions at end of backtest
            self._close_all_positions(
                exit_reason=ExitReason.END_OF_BACKTEST, 
                notes="End of backtest"
            )
            
            # Calculate final metrics
            self._finalize_results(run_record)
            
            logger.info("Backtest completed successfully")
            return run_record
            
        except Exception as e:
            logger.error(f"Backtest failed: {str(e)}", exc_info=True)
            run_record.status = "FAILED"
            self.db.commit()
            raise
            
    def _process_day(self, trade_date: date):
        """Process a single trading day."""
        # 1. Update market data context
        # In a real implementation, we might pre-fetch data here
        
        # 2. Check for exits on existing positions
        self._check_exits(trade_date)
        
        # 3. Generate and process new signals
        self._process_signals(trade_date)
        
        # 4. Mark to market and record daily equity
        self._update_daily_stats(trade_date)
        
    def _check_exits(self, trade_date: date):
        """Check exit conditions for all open positions."""
        # Iterate over a copy since we might remove items
        for position in list(self.positions):
            # Get current quote
            quote = self.data_provider.get_option_quote(
                position.underlying,
                position.expiration,
                position.strike,
                position.option_type,
                datetime.combine(trade_date, datetime.min.time().replace(hour=16))
            )
            
            if not quote:
                logger.warning(f"No quote for {position.underlying} {position.strike} {position.option_type} on {trade_date}")
                continue
                
            # Update MFE/MAE
            position.update_extremes(quote.mid)
            
            # Check expiration
            if trade_date >= position.expiration:
                self._close_position(position, quote.mid, trade_date, ExitReason.TIME_EXIT)
                continue
                
            # Check stop loss
            pnl_pct = (quote.mid - position.entry_price) / position.entry_price
            if self.config.stop_loss_pct and pnl_pct <= -self.config.stop_loss_pct:
                self._close_position(position, quote.mid, trade_date, ExitReason.STOP_LOSS)
                continue
                
            # Check take profit
            if self.config.profit_target_pct and pnl_pct >= self.config.profit_target_pct:
                self._close_position(position, quote.mid, trade_date, ExitReason.PROFIT_TARGET)
                continue
                
            # Check holding period
            holding_days = (trade_date - position.entry_date).days
            if self.config.max_hold_days and holding_days >= self.config.max_hold_days:
                self._close_position(position, quote.mid, trade_date, ExitReason.TIME_EXIT)
                continue
                
    def _process_signals(self, trade_date: date):
        """
        Generate and execute entry signals.
        
        In a full implementation, this would query the database for 
        EnsembleDecision or DailyBrief records for the given date.
        For now, we'll use a simplified logic or mock signals.
        """
        # Check if we have capital available
        if self.cash < self.config.min_cash_buffer:
            return
            
        # Check max positions
        if len(self.positions) >= self.config.max_open_positions:
            return
            
        # Fetch signals from DB (simplified)
        # In reality, we'd join Session, DailyBrief, EnsembleDecision
        # For this implementation, we'll assume we can get a signal
        signal = self._get_signal_from_db(trade_date)
        
        if signal and self._validate_signal(signal):
            self._execute_entry(signal, trade_date)
            
    def _get_signal_from_db(self, trade_date: date) -> Optional[Dict]:
        """
        Retrieve signal from database for the given date.
        
        This is where we integrate with the existing UWD system.
        """
        # Example query logic (simplified)
        # We want to find a session for this date
        stmt = select(DbSession).where(DbSession.date == trade_date)
        session = self.db.execute(stmt).scalars().first()
        
        if not session:
            return None
            
        # Check for ensemble decision
        # This assumes relationships are set up or we query directly
        # For now, let's mock a signal if we have a session
        # In production, this would read actual decision logic
        
        # Mock logic: Buy a call if regime is bullish, put if bearish
        # This requires the regime data to be populated
        return {
            "underlying": "SPY",
            "direction": "BULLISH",  # or BEARISH
            "confidence": "HIGH"
        }

    def _validate_signal(self, signal: Dict) -> bool:
        """Filter signals based on config criteria."""
        # Check regime filters if configured
        # Check confidence thresholds
        return True
        
    def _execute_entry(self, signal: Dict, trade_date: date):
        """Execute entry order based on signal."""
        underlying = signal["underlying"]
        direction = signal["direction"]
        
        # Determine option parameters
        # Target 30-45 DTE, ~30 delta
        target_dte = 30
        expiration = trade_date + timedelta(days=target_dte)
        
        # Find closest expiration in data (simplified)
        # In reality, we'd query the chain to find valid expiration
        
        # Determine strike
        # We need the underlying price first
        u_quote = self.data_provider.get_underlying_quote(
            underlying, 
            datetime.combine(trade_date, datetime.min.time().replace(hour=16))
        )
        
        if not u_quote:
            return
            
        # Simple strike selection: ATM
        strike = u_quote.close.quantize(Decimal("1.0"))
        option_type = "CALL" if direction == "BULLISH" else "PUT"
        
        # Get quote
        quote = self.data_provider.get_option_quote(
            underlying, expiration, strike, option_type,
            datetime.combine(trade_date, datetime.min.time().replace(hour=16))
        )
        
        if not quote:
            return
            
        # Calculate position size
        # Risk 2% of equity per trade
        risk_amount = self.equity * Decimal("0.02")
        contract_price = quote.ask * 100  # 100 multiplier
        
        if contract_price == 0:
            return
            
        quantity = int(risk_amount / contract_price)
        if quantity < 1:
            return
            
        # Apply slippage and commission
        entry_price = quote.ask * (1 + self.config.slippage_pct)
        cost = (entry_price * 100 * quantity) + (self.config.commission_per_contract * quantity)
        
        if cost > self.cash:
            quantity = int(self.cash / (entry_price * 100))
            if quantity < 1:
                return
            cost = (entry_price * 100 * quantity) + (self.config.commission_per_contract * quantity)
            
        # Record trade
        self.cash -= cost
        
        position = SimulatedPositionState(
            entry_date=trade_date,
            underlying=underlying,
            expiration=expiration,
            strike=strike,
            option_type=option_type,
            quantity=quantity,
            entry_price=entry_price,
            current_price=quote.mid,
            highest_price=quote.mid,
            lowest_price=quote.mid
        )
        self.positions.append(position)
        
        logger.debug(f"Entered {quantity} {underlying} {expiration} {strike} {option_type} @ {entry_price}")

    def _close_position(
        self, 
        position: SimulatedPositionState, 
        price: Decimal, 
        trade_date: date, 
        reason: ExitReason
    ):
        """Close a position and record the trade."""
        # Apply slippage and commission
        exit_price = price * (1 - self.config.slippage_pct)
        proceeds = (exit_price * 100 * position.quantity) - (self.config.commission_per_contract * position.quantity)
        
        self.cash += proceeds
        
        # Calculate PnL
        entry_cost = (position.entry_price * 100 * position.quantity) + (self.config.commission_per_contract * position.quantity)
        pnl = proceeds - entry_cost
        pnl_pct = (pnl / entry_cost) * 100 if entry_cost > 0 else 0
        
        # Create trade record
        trade = SimulatedTrade(
            backtest_run_id=self.run_id,
            symbol=position.underlying,
            entry_date=position.entry_date,
            exit_date=trade_date,
            option_type=position.option_type,
            strike=position.strike,
            expiration=position.expiration,
            dte_at_entry=(position.expiration - position.entry_date).days,
            entry_price=position.entry_price,
            exit_price=exit_price,
            contracts=position.quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            max_favorable_excursion=position.max_favorable_excursion,
            max_adverse_excursion=position.max_adverse_excursion,
            holding_period=(trade_date - position.entry_date).days
        )
        
        self.db.add(trade)
        self.closed_trades.append(trade)
        self.positions.remove(position)
        
        logger.debug(f"Closed {position.underlying} trade for PnL: {pnl:.2f} ({reason.value})")

    def _close_all_positions(self, exit_reason: ExitReason, notes: str):
        """Force close all positions (e.g., at end of backtest)."""
        for position in list(self.positions):
            # Get last known price
            quote = self.data_provider.get_option_quote(
                position.underlying,
                position.expiration,
                position.strike,
                position.option_type,
                datetime.combine(self.current_date, datetime.min.time().replace(hour=16))
            )
            price = quote.mid if quote else position.current_price
            self._close_position(position, price, self.current_date, exit_reason)

    def _update_daily_stats(self, trade_date: date):
        """Calculate daily equity and record stats."""
        # Calculate open position value
        open_position_value = Decimal("0")
        for pos in self.positions:
            # Update current price if we haven't already
            # (In optimized version, we'd reuse quotes)
            quote = self.data_provider.get_option_quote(
                pos.underlying,
                pos.expiration,
                pos.strike,
                pos.option_type,
                datetime.combine(trade_date, datetime.min.time().replace(hour=16))
            )
            if quote:
                pos.current_price = quote.mid
                
            open_position_value += pos.current_price * 100 * pos.quantity
            
        total_equity = self.cash + open_position_value
        self.equity = total_equity
        
        # Update high water mark and drawdown
        if total_equity > self.high_water_mark:
            self.high_water_mark = total_equity
        
        drawdown = Decimal("0")
        if self.high_water_mark > 0:
            drawdown = (self.high_water_mark - total_equity) / self.high_water_mark
        self.drawdown = drawdown
        
        # Record daily curve
        daily_stat = DailyEquityCurve(
            backtest_run_id=self.run_id,
            date=trade_date,
            portfolio_value=total_equity,
            cash_balance=self.cash,
            drawdown_pct=drawdown * 100,
            open_positions_count=len(self.positions),
            peak_value=self.high_water_mark
        )
        self.db.add(daily_stat)
        self.equity_curve.append(daily_stat)
        
        # Commit periodically to avoid massive transactions
        if trade_date.day == 1:  # Monthly commit
            self.db.commit()

    def _finalize_results(self, run_record: BacktestRun):
        """Calculate final metrics and update run record."""
        calc = PerformanceCalculator(
            trades=self.closed_trades,
            equity_curve=self.equity_curve,
            initial_capital=float(self.config.initial_capital)
        )
        metrics = calc.calculate()
        
        # Update run record with metrics
        run_record.performance_summary = metrics.to_dict()
        run_record.status = "COMPLETED"
        
        self.db.commit()
