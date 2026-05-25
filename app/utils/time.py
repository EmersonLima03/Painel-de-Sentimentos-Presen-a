"""Utilitários de tempo."""

from datetime import datetime, time
from typing import List, Tuple, Optional


def parse_time_window(window_str: str) -> Tuple[time, time]:
    """Parse uma janela de tempo no formato 'HH:MM-HH:MM'."""
    parts = window_str.split("-")
    if len(parts) != 2:
        raise ValueError(f"Formato inválido: {window_str}. Use 'HH:MM-HH:MM'")
    
    start = datetime.strptime(parts[0].strip(), "%H:%M").time()
    end = datetime.strptime(parts[1].strip(), "%H:%M").time()
    return start, end


def parse_active_windows(windows_str: str) -> List[Tuple[time, time]]:
    """Parse múltiplas janelas separadas por vírgula."""
    windows = []
    for w in windows_str.split(","):
        w = w.strip()
        if w:
            windows.append(parse_time_window(w))
    return windows


def is_in_active_window(active_windows: List[Tuple[time, time]], now: Optional[datetime] = None) -> bool:
    """Verifica se o horário atual está em alguma janela ativa."""
    if now is None:
        now = datetime.now()
    
    current_time = now.time()
    
    for start, end in active_windows:
        if start <= end:  # Janela normal (ex: 07:00-07:20)
            if start <= current_time <= end:
                return True
        else:  # Janela que cruza meia-noite (ex: 22:00-02:00)
            if current_time >= start or current_time <= end:
                return True
    
    return False


def get_date_key(dt: Optional[datetime] = None) -> str:
    """Retorna chave de data no formato YYYY-MM-DD."""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d")
