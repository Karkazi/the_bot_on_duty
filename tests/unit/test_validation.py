"""
Unit тесты для модуля validation.
"""
import pytest
from datetime import datetime
from utils.validation import (
    sanitize_html,
    validate_text_length,
    validate_title,
    validate_description,
    validate_message_text,
    validate_datetime_format
)


class TestSanitizeHTML:
    """Тесты для функции sanitize_html"""
    
    def test_sanitize_basic_html(self):
        """Тест экранирования базовых HTML тегов"""
        result = sanitize_html("<script>alert('xss')</script>")
        assert "&lt;script&gt;" in result
        assert "&lt;/script&gt;" in result
    
    def test_sanitize_quotes(self):
        """Тест экранирования кавычек"""
        result = sanitize_html('Text with "quotes"')
        assert "&quot;" in result
    
    def test_sanitize_ampersand(self):
        """Тест экранирования амперсанда"""
        result = sanitize_html("A & B")
        assert "&amp;" in result


class TestValidateTextLength:
    """Тесты для функции validate_text_length"""
    
    def test_valid_length(self):
        """Тест валидной длины"""
        is_valid, error = validate_text_length("test", 10, "text")
        assert is_valid is True
        assert error is None
    
    def test_too_long(self):
        """Тест слишком длинного текста"""
        is_valid, error = validate_text_length("a" * 11, 10, "text")
        assert is_valid is False
        assert error is not None
        assert "10" in error


class TestValidateTitle:
    """Тесты для функции validate_title"""
    
    def test_valid_title(self):
        """Тест валидного заголовка"""
        is_valid, error = validate_title("Valid Title")
        assert is_valid is True
        assert error is None
    
    def test_empty_title(self):
        """Тест пустого заголовка"""
        is_valid, error = validate_title("")
        assert is_valid is False
        assert error is not None
    
    def test_whitespace_only_title(self):
        """Тест заголовка только с пробелами"""
        is_valid, error = validate_title("   ")
        assert is_valid is False


class TestValidateDescription:
    """Тесты для функции validate_description"""
    
    def test_valid_description(self):
        """Тест валидного описания"""
        is_valid, error = validate_description("Valid description")
        assert is_valid is True
        assert error is None
    
    def test_empty_description(self):
        """Тест пустого описания"""
        is_valid, error = validate_description("")
        assert is_valid is False


class TestValidateMessageText:
    """Тесты для функции validate_message_text"""
    
    def test_valid_message_text(self):
        """Тест валидного текста сообщения"""
        is_valid, error = validate_message_text("Valid message")
        assert is_valid is True
        assert error is None
    
    def test_empty_message_text(self):
        """Тест пустого текста сообщения"""
        is_valid, error = validate_message_text("")
        assert is_valid is False


class TestValidateDatetimeFormat:
    """Тесты для функции validate_datetime_format"""
    
    def test_valid_datetime(self):
        """Тест валидной даты"""
        is_valid, error = validate_datetime_format("27.05.2025 14:00", "%d.%m.%Y %H:%M")
        assert is_valid is True
        assert error is None
    
    def test_invalid_format(self):
        """Тест неверного формата"""
        is_valid, error = validate_datetime_format("2025-05-27 14:00", "%d.%m.%Y %H:%M")
        assert is_valid is False
        assert error is not None
    
    def test_invalid_date(self):
        """Тест неверной даты"""
        is_valid, error = validate_datetime_format("32.13.2025 25:00", "%d.%m.%Y %H:%M")
        assert is_valid is False

