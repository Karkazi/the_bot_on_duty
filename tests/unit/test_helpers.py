"""
Unit тесты для модуля helpers.
"""
import pytest
from datetime import timedelta
from utils.helpers import parse_duration


class TestParseDuration:
    """Тесты для функции parse_duration"""
    
    def test_parse_hours(self):
        """Тест парсинга часов"""
        result = parse_duration("1 час")
        assert result == timedelta(hours=1)
    
    def test_parse_minutes(self):
        """Тест парсинга минут"""
        result = parse_duration("30 минут")
        assert result == timedelta(minutes=30)
    
    def test_parse_days(self):
        """Тест парсинга дней"""
        result = parse_duration("2 дня")
        assert result == timedelta(days=2)
    
    def test_parse_with_through(self):
        """Тест парсинга с 'через'"""
        result = parse_duration("через 1 час")
        assert result == timedelta(hours=1)
    
    def test_parse_decimal_hours(self):
        """Тест парсинга дробных часов"""
        result = parse_duration("1.5 часа")
        assert result == timedelta(hours=1.5)
    
    def test_parse_invalid(self):
        """Тест парсинга невалидной строки"""
        result = parse_duration("invalid")
        assert result is None
    
    def test_parse_empty(self):
        """Тест парсинга пустой строки"""
        result = parse_duration("")
        assert result is None
    
    def test_parse_with_comma(self):
        """Тест парсинга с запятой"""
        result = parse_duration("1,5 часа")
        assert result == timedelta(hours=1.5)

