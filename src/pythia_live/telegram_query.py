"""
Telegram Bot Commands for Pythia Query Interface.

Traders can query historical spikes via Telegram bot commands:
/fed_rate 5% — Show Fed rate spikes ≥5%
/similar Bitcoin — Find similar BTC spikes  
/what_caused 42 — Show what caused spike #42
/patterns — Show discovered causal patterns
/correlations 0xabc — Show correlated movements
"""
import logging
import re
from typing import Optional

from .database import PythiaDB
from .spike_archive import get_spike_history
from .patterns import build_patterns, find_matching_pattern, _categorize_market

logger = logging.getLogger(__name__)


class TelegramQueryHandler:
    """Handle query commands via Telegram bot."""
    
    def __init__(self, db_path: str = 'data/pythia_live.db'):
        self.db = PythiaDB(db_path)
    
    def handle_command(self, command: str, args: str) -> str:
        """
        Process a Telegram command and return response text.
        
        Commands:
          /fed_rate [min%] — Fed rate spikes
          /similar <market> — Find similar spikes
          /what_caused <id> — Show attribution
          /patterns — List patterns
          /correlations <market_id> — Show correlations
        """
        command = command.lower().lstrip('/')
        
        if command in ['fed_rate', 'fed', 'fedrate']:
            return self._cmd_fed_rate(args)
        elif command == 'similar':
            return self._cmd_similar(args)
        elif command == 'what_caused':
            return self._cmd_what_caused(args)
        elif command == 'patterns':
            return self._cmd_patterns()
        elif command == 'correlations':
            return self._cmd_correlations(args)
        elif command in ['help', 'start']:
            return self._cmd_help()
        else:
            return f"Unknown command: /{command}\nTry /help"
    
    def _cmd_fed_rate(self, args: str) -> str:
        """Query Fed rate spikes."""
        min_mag = 0.05  # Default 5%
        
        # Parse percentage if provided
        if args:
            match = re.search(r'(\d+)', args.replace('%', ''))
            if match:
                min_mag = int(match.group(1)) / 100
        
        spikes = get_spike_history(self.db, min_magnitude=min_mag, limit=50)
        fed_spikes = [s for s in spikes if _categorize_market(s.market_title) == 'fed_rate']
        
        if not fed_spikes:
            return f"No Fed rate spikes ≥{min_mag:.0%} found."
        
        lines = [f"FED RATE SPIKES (≥{min_mag:.0%})", ""]
        
        for spike in fed_spikes[:5]:
            date_str = spike.timestamp.strftime('%m/%d %H:%M')
            lines.append(f"• {spike.direction.upper()} {spike.magnitude:.1%} on {date_str}")
            lines.append(f"  {spike.market_title[:50]}...")
            if spike.attributed_events:
                cause = spike.attributed_events[0].get('headline', 'Unknown')[:40]
                lines.append(f"  Cause: {cause}...")
            lines.append("")
        
        if len(fed_spikes) > 5:
            lines.append(f"...and {len(fed_spikes) - 5} more")
        
        return '\n'.join(lines)
    
    def _cmd_similar(self, args: str) -> str:
        """Find similar spikes."""
        if not args:
            return "Usage: /similar <market name>\nExample: /similar Bitcoin"
        
        category = _categorize_market(args)
        spikes = get_spike_history(self.db, min_magnitude=0.03, limit=100)
        similar = [s for s in spikes if _categorize_market(s.market_title) == category]
        
        if not similar:
            return f"No spikes found in category: {category}"
        
        lines = [f"SPIKES SIMILAR TO: {args}", f"Category: {category}", ""]
        
        for spike in similar[:5]:
            date_str = spike.timestamp.strftime('%m/%d')
            lines.append(f"• {spike.direction.upper()} {spike.magnitude:.1%} ({date_str})")
            lines.append(f"  {spike.market_title[:45]}...")
            lines.append("")
        
        return '\n'.join(lines)
    
    def _cmd_what_caused(self, args: str) -> str:
        """Show what caused a spike."""
        if not args:
            return "Usage: /what_caused <spike_id>\nExample: /what_caused 42"
        
        try:
            spike_id = int(args.strip())
        except ValueError:
            return "Invalid spike ID. Use: /what_caused 42"
        
        spikes = get_spike_history(self.db, min_magnitude=0.01, limit=200)
        spike = next((s for s in spikes if s.id == spike_id), None)
        
        if not spike:
            return f"Spike #{spike_id} not found."
        
        date_str = spike.timestamp.strftime('%Y-%m-%d %H:%M')
        lines = [
            f"SPIKE #{spike.id}",
            f"Market: {spike.market_title[:50]}...",
            f"Time: {date_str}",
            f"Move: {spike.direction.upper()} {spike.magnitude:.1%}",
            ""
        ]
        
        if spike.attributed_events:
            lines.append("ATTRIBUTED CAUSES:")
            for i, evt in enumerate(spike.attributed_events[:3], 1):
                headline = evt.get('headline', 'Unknown')[:60]
                source = evt.get('source', 'unknown')
                lines.append(f"{i}. {headline}...")
                lines.append(f"   Source: {source}")
                lines.append("")
        else:
            lines.append("No attribution data available.")
            lines.append("(Requires active news search at time of spike)")
        
        return '\n'.join(lines)
    
    def _cmd_patterns(self) -> str:
        """Show discovered patterns."""
        patterns = build_patterns(self.db)
        
        if not patterns:
            return "No patterns discovered yet. Need more spike data."
        
        lines = ["CAUSAL PATTERNS", f"Found {len(patterns)} patterns", ""]
        
        for p in patterns[:8]:
            conf = 'HIGH' if p.confidence >= 0.7 else 'MED' if p.confidence >= 0.5 else 'LOW'
            lines.append(f"• {p.market_category.upper()} / {p.direction.upper()}")
            lines.append(f"  Samples: {p.sample_size} | Avg: {p.avg_magnitude:.1%} | Conf: {conf}")
            if p.typical_cause:
                lines.append(f"  Typical cause: {p.typical_cause}")
            lines.append("")
        
        if len(patterns) > 8:
            lines.append(f"...and {len(patterns) - 8} more patterns")
        
        return '\n'.join(lines)
    
    def _cmd_correlations(self, args: str) -> str:
        """Show correlated movements."""
        if not args:
            return "Usage: /correlations <market_id>\nExample: /correlations 0xabc123..."
        
        market_id = args.strip()
        spikes = get_spike_history(self.db, market_id=market_id, min_magnitude=0.03, limit=1)
        
        if not spikes:
            return f"No spike found for market: {market_id[:20]}..."
        
        spike = spikes[0]
        from datetime import timedelta
        
        # Find correlated spikes
        all_spikes = get_spike_history(self.db, min_magnitude=0.03, limit=100)
        correlated = []
        for s in all_spikes:
            if s.id == spike.id:
                continue
            time_diff = abs((s.timestamp - spike.timestamp).total_seconds())
            if time_diff <= 7200:  # 2 hours
                correlated.append((s, time_diff))
        
        date_str = spike.timestamp.strftime('%m/%d %H:%M')
        lines = [
            f"CORRELATIONS FOR: {spike.market_title[:40]}...",
            f"Reference: {spike.direction.upper()} {spike.magnitude:.1%} on {date_str}",
            ""
        ]
        
        if correlated:
            lines.append("Correlated moves (within 2 hours):")
            for s, diff in sorted(correlated, key=lambda x: x[1])[:5]:
                mins = int(diff / 60)
                prefix = "+" if mins >= 0 else ""
                lines.append(f"• {prefix}{mins}min: {s.direction.upper()} {s.magnitude:.1%}")
                lines.append(f"  {s.market_title[:40]}...")
        else:
            lines.append("No correlated spikes found within 2-hour window.")
        
        return '\n'.join(lines)
    
    def _cmd_help(self) -> str:
        """Show help message."""
        return """
PYTHIA QUERY COMMANDS

Query historical prediction market spikes and their causes.

/fed_rate [5%] — Show Fed rate spikes
/similar Bitcoin — Find similar market spikes  
/what_caused 42 — Show what caused spike #42
/patterns — List discovered causal patterns
/correlations 0xabc — Show correlated movements

Examples:
  /fed_rate 10%
  /similar "Fed rate cut"
  /patterns

Try /patterns to see what Pythia has learned so far.
        """.strip()


def handle_telegram_command(message_text: str, db_path: str = 'data/pythia_live.db') -> str:
    """
    Convenience function for Telegram bot integration.
    
    Usage in your Telegram bot:
        from pythia_live.telegram_query import handle_telegram_command
        
        if message.startswith('/'):
            response = handle_telegram_command(message)
            bot.send_message(chat_id, response)
    """
    # Parse command and args
    parts = message_text.split(maxsplit=1)
    command = parts[0] if parts else ''
    args = parts[1] if len(parts) > 1 else ''
    
    handler = TelegramQueryHandler(db_path)
    return handler.handle_command(command, args)
