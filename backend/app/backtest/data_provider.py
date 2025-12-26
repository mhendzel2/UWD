"""
Data provider abstraction for backtesting.

Provides an interface for fetching price data during backtests.
Implementations can fetch from databases, CSV files, or external APIs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class OptionQuote:
    """Snapshot of option pricing at a point in time."""
    
    underlying: str
    expiration: date
    strike: Decimal
    option_type: str  # 'CALL' or 'PUT'
    timestamp: datetime
    
    # Prices
    bid: Decimal
    ask: Decimal
    mid: Decimal
    last: Optional[Decimal] = None
    
    # Greeks (optional, for analysis)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None
    
    # Volume/OI
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    
    @property
    def spread(self) -> Decimal:
        """Bid-ask spread."""
        return self.ask - self.bid
    
    @property
    def spread_pct(self) -> float:
        """Spread as percentage of mid price."""
        if self.mid == 0:
            return float('inf')
        return float(self.spread / self.mid) * 100


@dataclass
class UnderlyingQuote:
    """Snapshot of underlying stock/ETF pricing."""
    
    symbol: str
    timestamp: datetime
    
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    
    # Optional intraday data
    vwap: Optional[Decimal] = None
    
    @property
    def range_pct(self) -> float:
        """Daily range as percentage of open."""
        if self.open == 0:
            return 0.0
        return float((self.high - self.low) / self.open) * 100


@dataclass
class PriceBar:
    """OHLCV bar for any timeframe."""
    
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class DataProvider(ABC):
    """
    Abstract base class for price data providers.
    
    Implementations should handle caching and rate limiting internally.
    """
    
    @abstractmethod
    def get_option_quote(
        self,
        underlying: str,
        expiration: date,
        strike: Decimal,
        option_type: str,
        as_of: datetime
    ) -> Optional[OptionQuote]:
        """
        Get option quote as of a specific datetime.
        
        Args:
            underlying: Underlying symbol (e.g., 'SPY')
            expiration: Option expiration date
            strike: Strike price
            option_type: 'CALL' or 'PUT'
            as_of: Timestamp to get quote for
            
        Returns:
            OptionQuote if available, None otherwise
        """
        pass
    
    @abstractmethod
    def get_underlying_quote(
        self,
        symbol: str,
        as_of: datetime
    ) -> Optional[UnderlyingQuote]:
        """
        Get underlying quote as of a specific datetime.
        
        Args:
            symbol: Ticker symbol
            as_of: Timestamp to get quote for
            
        Returns:
            UnderlyingQuote if available, None otherwise
        """
        pass
    
    @abstractmethod
    def get_option_chain(
        self,
        underlying: str,
        expiration: date,
        as_of: datetime
    ) -> List[OptionQuote]:
        """
        Get full option chain for an expiration.
        
        Args:
            underlying: Underlying symbol
            expiration: Option expiration date
            as_of: Timestamp to get chain for
            
        Returns:
            List of OptionQuotes for all strikes
        """
        pass
    
    @abstractmethod
    def get_price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        interval: str = '1d'
    ) -> List[PriceBar]:
        """
        Get historical price bars.
        
        Args:
            symbol: Ticker symbol
            start_date: Start of date range
            end_date: End of date range
            interval: Bar interval ('1m', '5m', '1h', '1d')
            
        Returns:
            List of PriceBars
        """
        pass


class MockDataProvider(DataProvider):
    """
    Mock data provider for testing and development.
    
    Generates synthetic price data based on configurable parameters.
    Useful for testing backtesting logic without real data.
    """
    
    def __init__(
        self,
        base_underlying_price: Decimal = Decimal("450.00"),
        daily_volatility: float = 0.015,
        option_iv: float = 0.20,
        bid_ask_spread_pct: float = 0.02
    ):
        self.base_price = base_underlying_price
        self.daily_vol = daily_volatility
        self.option_iv = option_iv
        self.spread_pct = bid_ask_spread_pct
        self._price_cache: Dict[str, Dict[date, Decimal]] = {}
        
    def _get_underlying_price_for_date(self, symbol: str, for_date: date) -> Decimal:
        """Generate consistent underlying price for a date."""
        if symbol not in self._price_cache:
            self._price_cache[symbol] = {}
            
        if for_date not in self._price_cache[symbol]:
            # Use date as seed for reproducibility
            import random
            seed = hash((symbol, for_date.isoformat()))
            rng = random.Random(seed)
            
            # Random walk from base price
            days_offset = (for_date - date(2024, 1, 1)).days
            cumulative_return = sum(
                rng.gauss(0.0003, self.daily_vol) 
                for _ in range(days_offset % 252)
            )
            price = self.base_price * Decimal(str(1 + cumulative_return))
            self._price_cache[symbol][for_date] = price.quantize(Decimal("0.01"))
            
        return self._price_cache[symbol][for_date]
    
    def get_option_quote(
        self,
        underlying: str,
        expiration: date,
        strike: Decimal,
        option_type: str,
        as_of: datetime
    ) -> Optional[OptionQuote]:
        """Generate synthetic option quote."""
        underlying_price = self._get_underlying_price_for_date(underlying, as_of.date())
        
        # Calculate time to expiration
        dte = (expiration - as_of.date()).days
        if dte < 0:
            return None
            
        t = max(dte / 365.0, 0.001)
        
        # Simplified Black-Scholes-ish pricing
        import math
        
        moneyness = float(underlying_price / strike)
        intrinsic = max(
            float(underlying_price - strike) if option_type == 'CALL' 
            else float(strike - underlying_price),
            0
        )
        
        # Time value based on IV and DTE
        time_value = float(underlying_price) * self.option_iv * math.sqrt(t) * 0.4
        
        # Adjust for moneyness
        if option_type == 'CALL':
            otm_factor = max(0.1, min(1.0, moneyness))
        else:
            otm_factor = max(0.1, min(1.0, 1 / moneyness))
            
        mid_price = Decimal(str(intrinsic + time_value * otm_factor)).quantize(Decimal("0.01"))
        mid_price = max(mid_price, Decimal("0.01"))
        
        spread = mid_price * Decimal(str(self.spread_pct))
        spread = max(spread, Decimal("0.01")).quantize(Decimal("0.01"))
        
        bid = (mid_price - spread / 2).quantize(Decimal("0.01"))
        ask = (mid_price + spread / 2).quantize(Decimal("0.01"))
        bid = max(bid, Decimal("0.01"))
        
        # Simplified delta
        if option_type == 'CALL':
            delta = max(0.01, min(0.99, 0.5 + (moneyness - 1) * 2))
        else:
            delta = -max(0.01, min(0.99, 0.5 - (moneyness - 1) * 2))
        
        return OptionQuote(
            underlying=underlying,
            expiration=expiration,
            strike=strike,
            option_type=option_type,
            timestamp=as_of,
            bid=bid,
            ask=ask,
            mid=mid_price,
            delta=delta,
            iv=self.option_iv,
            volume=1000,
            open_interest=5000
        )
    
    def get_underlying_quote(
        self,
        symbol: str,
        as_of: datetime
    ) -> Optional[UnderlyingQuote]:
        """Generate synthetic underlying quote."""
        close = self._get_underlying_price_for_date(symbol, as_of.date())
        
        # Generate OHLC around close
        import random
        rng = random.Random(hash((symbol, as_of.date().isoformat())))
        
        daily_range = float(close) * self.daily_vol * 2
        
        high = close + Decimal(str(rng.uniform(0, daily_range / 2))).quantize(Decimal("0.01"))
        low = close - Decimal(str(rng.uniform(0, daily_range / 2))).quantize(Decimal("0.01"))
        open_price = Decimal(str(
            rng.uniform(float(low), float(high))
        )).quantize(Decimal("0.01"))
        
        return UnderlyingQuote(
            symbol=symbol,
            timestamp=as_of,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=rng.randint(10_000_000, 100_000_000)
        )
    
    def get_option_chain(
        self,
        underlying: str,
        expiration: date,
        as_of: datetime
    ) -> List[OptionQuote]:
        """Generate synthetic option chain."""
        underlying_price = self._get_underlying_price_for_date(underlying, as_of.date())
        
        # Generate strikes around the money
        base_strike = int(underlying_price)
        strikes = [
            Decimal(str(base_strike + offset))
            for offset in range(-20, 21)  # 41 strikes
        ]
        
        quotes = []
        for strike in strikes:
            for opt_type in ['CALL', 'PUT']:
                quote = self.get_option_quote(
                    underlying, expiration, strike, opt_type, as_of
                )
                if quote:
                    quotes.append(quote)
                    
        return quotes
    
    def get_price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        interval: str = '1d'
    ) -> List[PriceBar]:
        """Generate synthetic price history."""
        from datetime import timedelta
        
        bars = []
        current = start_date
        
        while current <= end_date:
            # Skip weekends
            if current.weekday() < 5:
                quote = self.get_underlying_quote(
                    symbol, 
                    datetime.combine(current, datetime.min.time().replace(hour=16))
                )
                if quote:
                    bars.append(PriceBar(
                        timestamp=datetime.combine(current, datetime.min.time().replace(hour=16)),
                        open=quote.open,
                        high=quote.high,
                        low=quote.low,
                        close=quote.close,
                        volume=quote.volume
                    ))
            current += timedelta(days=1)
            
        return bars


class CsvDataProvider(DataProvider):
    """
    Data provider that reads from CSV files.
    
    Expected file structure:
    - underlying_prices.csv: date,symbol,open,high,low,close,volume
    - option_quotes.csv: date,underlying,expiration,strike,type,bid,ask,volume,oi
    """
    
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._underlying_data: Dict[str, Dict[date, UnderlyingQuote]] = {}
        self._option_data: Dict[str, Dict[date, List[OptionQuote]]] = {}
        self._loaded = False
        
    def _load_data(self):
        """Load CSV files into memory."""
        if self._loaded:
            return
            
        import os
        import csv
        from pathlib import Path
        
        data_path = Path(self.data_dir)
        
        # Load underlying prices
        underlying_file = data_path / "underlying_prices.csv"
        if underlying_file.exists():
            with open(underlying_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    symbol = row['symbol']
                    trade_date = date.fromisoformat(row['date'])
                    
                    if symbol not in self._underlying_data:
                        self._underlying_data[symbol] = {}
                        
                    self._underlying_data[symbol][trade_date] = UnderlyingQuote(
                        symbol=symbol,
                        timestamp=datetime.combine(trade_date, datetime.min.time().replace(hour=16)),
                        open=Decimal(row['open']),
                        high=Decimal(row['high']),
                        low=Decimal(row['low']),
                        close=Decimal(row['close']),
                        volume=int(row['volume'])
                    )
                    
        # Load option quotes
        option_file = data_path / "option_quotes.csv"
        if option_file.exists():
            with open(option_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    underlying = row['underlying']
                    trade_date = date.fromisoformat(row['date'])
                    
                    key = f"{underlying}_{row['expiration']}"
                    if key not in self._option_data:
                        self._option_data[key] = {}
                    if trade_date not in self._option_data[key]:
                        self._option_data[key][trade_date] = []
                        
                    bid = Decimal(row['bid'])
                    ask = Decimal(row['ask'])
                    mid = (bid + ask) / 2
                    
                    self._option_data[key][trade_date].append(OptionQuote(
                        underlying=underlying,
                        expiration=date.fromisoformat(row['expiration']),
                        strike=Decimal(row['strike']),
                        option_type=row['type'].upper(),
                        timestamp=datetime.combine(trade_date, datetime.min.time().replace(hour=16)),
                        bid=bid,
                        ask=ask,
                        mid=mid,
                        volume=int(row.get('volume', 0)),
                        open_interest=int(row.get('oi', 0))
                    ))
                    
        self._loaded = True
        logger.info(f"Loaded {len(self._underlying_data)} underlyings, {len(self._option_data)} option chains")
        
    def get_option_quote(
        self,
        underlying: str,
        expiration: date,
        strike: Decimal,
        option_type: str,
        as_of: datetime
    ) -> Optional[OptionQuote]:
        """Get option quote from CSV data."""
        self._load_data()
        
        key = f"{underlying}_{expiration.isoformat()}"
        if key not in self._option_data:
            return None
            
        trade_date = as_of.date()
        if trade_date not in self._option_data[key]:
            return None
            
        for quote in self._option_data[key][trade_date]:
            if quote.strike == strike and quote.option_type == option_type.upper():
                return quote
                
        return None
    
    def get_underlying_quote(
        self,
        symbol: str,
        as_of: datetime
    ) -> Optional[UnderlyingQuote]:
        """Get underlying quote from CSV data."""
        self._load_data()
        
        if symbol not in self._underlying_data:
            return None
            
        trade_date = as_of.date()
        return self._underlying_data[symbol].get(trade_date)
    
    def get_option_chain(
        self,
        underlying: str,
        expiration: date,
        as_of: datetime
    ) -> List[OptionQuote]:
        """Get option chain from CSV data."""
        self._load_data()
        
        key = f"{underlying}_{expiration.isoformat()}"
        if key not in self._option_data:
            return []
            
        trade_date = as_of.date()
        return self._option_data[key].get(trade_date, [])
    
    def get_price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        interval: str = '1d'
    ) -> List[PriceBar]:
        """Get price history from CSV data."""
        self._load_data()
        
        if symbol not in self._underlying_data:
            return []
            
        bars = []
        for trade_date, quote in sorted(self._underlying_data[symbol].items()):
            if start_date <= trade_date <= end_date:
                bars.append(PriceBar(
                    timestamp=quote.timestamp,
                    open=quote.open,
                    high=quote.high,
                    low=quote.low,
                    close=quote.close,
                    volume=quote.volume
                ))
                
        return bars
