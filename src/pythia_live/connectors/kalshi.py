"""
Kalshi API Connector
Real-time market data from Kalshi exchange
"""
import requests
import base64
from typing import List, Dict, Optional
from datetime import datetime

class KalshiConnector:
    """
    Kalshi API for event contracts
    Docs: https://trading-api.readme.io/reference
    """
    
    BASE_URL = "https://trading-api.kalshi.com/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session = requests.Session()
        
        if api_key:
            # Kalshi uses Basic auth with API key
            encoded = base64.b64encode(f"{api_key}:".encode()).decode()
            self.session.headers.update({
                "Authorization": f"Basic {encoded}"
            })
    
    def get_active_markets(self, limit: int = 100) -> List[Dict]:
        """
        Fetch active markets from Kalshi.
        
        Note: Without API key, only public endpoints work.
        """
        try:
            # Public markets endpoint
            url = f"{self.BASE_URL}/markets"
            params = {
                "status": "active",
                "limit": limit
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            markets = []
            
            for market in data.get('markets', []):
                market_data = {
                    'id': market.get('ticker', market.get('id')),
                    'source': 'kalshi',
                    'title': market.get('title', market.get('question', 'Unknown')),
                    'category': market.get('category', 'General'),
                    'liquidity': float(market.get('volume', 0) or 0) * 0.1,  # Estimate
                    'volume_24h': float(market.get('volume', 0) or 0),
                    'description': market.get('description', ''),
                    'close_date': market.get('close_date'),
                    'created_at': market.get('created_at', datetime.now().isoformat())
                }
                markets.append(market_data)
                
            return markets
            
        except Exception as e:
            print(f"Kalshi API error: {e}")
            # Return empty list, we'll use cached data or skip
            return []
    
    def get_market_price(self, ticker: str) -> Optional[Dict]:
        """
        Get current price for a specific market.
        
        Note: Public endpoint returns last trade price.
        """
        try:
            url = f"{self.BASE_URL}/markets/{ticker}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            market = data.get('market', {})
            
            # Kalshi prices are 0-100 (cents), convert to 0-1
            yes_price = float(market.get('last_price', 50)) / 100
            
            return {
                'market_id': ticker,
                'yes_price': yes_price,
                'no_price': 1 - yes_price,
                'volume': float(market.get('volume', 0)),
                'open_interest': float(market.get('open_interest', 0)),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"Kalshi price fetch error for {ticker}: {e}")
            return None
    
    def get_series_markets(self, series_ticker: str) -> List[Dict]:
        """
        Get all markets in a series (e.g., "KXELON" for Elon-related).
        
        Useful for correlation arbitrage.
        """
        try:
            url = f"{self.BASE_URL}/series/{series_ticker}/markets"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            return response.json().get('markets', [])
            
        except Exception as e:
            print(f"Series fetch error: {e}")
            return []
