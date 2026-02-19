"""
Polymarket CLOB API Connector
Real-time market data
"""
import requests
import json
from typing import List, Dict, Optional
from datetime import datetime

class PolymarketConnector:
    """
    Polymarket CLOB (Central Limit Order Book) API
    REST API for market data
    """
    
    BASE_URL = "https://clob.polymarket.com"
    
    def __init__(self):
        self.session = requests.Session()
        
    def get_active_markets(self, limit: int = 100) -> List[Dict]:
        """
        Fetch active markets from Polymarket.
        
        Returns list of markets with liquidity info.
        """
        try:
            # Get markets with filtering
            url = f"{self.BASE_URL}/markets"
            params = {
                "active": "true",
                "closed": "false",
                "limit": limit
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            markets = []
            
            for market in data.get('data', []):
                # Extract relevant fields
                market_data = {
                    'id': market.get('condition_id', market.get('id')),
                    'source': 'polymarket',
                    'title': market.get('question', 'Unknown'),
                    'category': market.get('category', 'General'),
                    'liquidity': float(market.get('liquidity', 0) or 0),
                    'volume_24h': float(market.get('volume_24h', 0) or 0),
                    'description': market.get('description', ''),
                    'end_date': market.get('end_date'),
                    'created_at': market.get('created_at', datetime.now().isoformat())
                }
                markets.append(market_data)
                
            return markets
            
        except Exception as e:
            print(f"Polymarket API error: {e}")
            return []
    
    def get_market_price(self, market_id: str) -> Optional[Dict]:
        """
        Get current price for a specific market.
        
        Returns best bid/ask for yes/no tokens.
        """
        try:
            url = f"{self.BASE_URL}/markets/{market_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Get orderbook for YES token
            yes_token = data.get('yes_token_id') or data.get('tokens', [{}])[0].get('token_id')
            
            if yes_token:
                book_url = f"{self.BASE_URL}/book"
                book_response = self.session.get(book_url, params={"token_id": yes_token}, timeout=10)
                book_data = book_response.json()
                
                # Extract best prices
                bids = book_data.get('bids', [])
                asks = book_data.get('asks', [])
                
                best_bid = float(bids[0]['price']) if bids else 0.5
                best_ask = float(asks[0]['price']) if asks else 0.5
                
                return {
                    'market_id': market_id,
                    'yes_bid': best_bid,
                    'yes_ask': best_ask,
                    'no_bid': 1 - best_ask,
                    'no_ask': 1 - best_bid,
                    'mid_price': (best_bid + best_ask) / 2,
                    'spread': best_ask - best_bid,
                    'timestamp': datetime.now().isoformat()
                }
                
        except Exception as e:
            print(f"Price fetch error for {market_id}: {e}")
            return None
    
    def get_market_orderbook(self, market_id: str) -> Optional[Dict]:
        """Get full orderbook for market."""
        try:
            # First get token ID
            market_url = f"{self.BASE_URL}/markets/{market_id}"
            market_response = self.session.get(market_url, timeout=10)
            market_data = market_response.json()
            
            yes_token = market_data.get('yes_token_id') or market_data.get('tokens', [{}])[0].get('token_id')
            
            if yes_token:
                book_url = f"{self.BASE_URL}/book"
                response = self.session.get(book_url, params={"token_id": yes_token}, timeout=10)
                return response.json()
                
        except Exception as e:
            print(f"Orderbook error: {e}")
            return None
