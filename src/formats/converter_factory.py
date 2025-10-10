"""
转换器工厂
负责创建和管理不同格式的转换器
"""
from typing import Dict, Optional
from .base_converter import BaseConverter, ConversionResult
from .openai_converter import OpenAIConverter
from .anthropic_converter import AnthropicConverter
from .gemini_converter import GeminiConverter
from .responses_converter import ResponsesConverter
from src.utils.logger import setup_logger

logger = setup_logger("converter_factory")


class ConverterFactory:
    """转换器工厂"""
    
    _converters: Dict[str, BaseConverter] = {}
    
    @classmethod
    def get_converter(cls, format_name: str) -> Optional[BaseConverter]:
        """获取指定格式的转换器"""
        if format_name not in cls._converters:
            cls._converters[format_name] = cls._create_converter(format_name)
        
        return cls._converters[format_name]
    
    @classmethod
    def _create_converter(cls, format_name: str) -> Optional[BaseConverter]:
        """创建转换器实例"""
        converters = {
            "openai": OpenAIConverter,
            "anthropic": AnthropicConverter,
            "gemini": GeminiConverter,
            "responses": ResponsesConverter
        }

        converter_class = converters.get(format_name)
        if converter_class:
            logger.info(f"Created converter for format: {format_name}")
            return converter_class()
        else:
            logger.error(f"Unsupported format: {format_name}")
            return None
    
    @classmethod
    def get_supported_formats(cls) -> list[str]:
        """获取支持的格式列表"""
        return ["openai", "anthropic", "gemini", "responses"]
    
    @classmethod
    def is_format_supported(cls, format_name: str) -> bool:
        """检查格式是否支持"""
        return format_name in cls.get_supported_formats()


# 便捷函数
def convert_request(source_format: str, target_format: str, data: dict, headers: dict = None):
    """转换请求格式"""
    converter = ConverterFactory.get_converter(source_format)
    if not converter:
        raise ValueError(f"Unsupported source format: {source_format}")
    
    # 设置原始模型名称（如果存在）
    if hasattr(converter, 'set_original_model') and 'model' in data:
        converter.set_original_model(data['model'])
    
    return converter.convert_request(data, target_format, headers)


def convert_response(source_format: str, target_format: str, data: dict, original_model: str = None):
    """转换响应格式"""
    converter = ConverterFactory.get_converter(target_format)
    if not converter:
        raise ValueError(f"Unsupported target format: {target_format}")
    
    # 传递原始模型名称给转换器
    if hasattr(converter, 'set_original_model') and original_model:
        converter.set_original_model(original_model)
    
    return converter.convert_response(data, source_format, target_format)


def convert_streaming_chunk(source_format: str, target_format: str, data: dict, original_model: str = None):
    """转换流式响应chunk格式"""
    import logging
    # 使用与unified_api相同的logger名称确保日志输出
    logger = logging.getLogger("unified_api")
    logger.debug(f"CONVERTER_FACTORY: convert_streaming_chunk called: {source_format} -> {target_format}")
    logger.debug(f"CONVERTER_FACTORY: Data type: {type(data)}, keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
    
    # 验证输入参数
    if not data:
        logger.warning(f"Empty data passed to convert_streaming_chunk")
        return ConversionResult(success=True, data={})
    
    # 如果源格式和目标格式相同，直接返回原始数据（无需转换）
    if source_format == target_format:
        logger.debug(f"Same format ({source_format}), returning data without conversion")
        return ConversionResult(success=True, data=data)
    
    converter = ConverterFactory.get_converter(target_format)
    if not converter:
        raise ValueError(f"Unsupported target format: {target_format}")
    
    # 传递原始模型名称给转换器
    if hasattr(converter, 'set_original_model') and original_model:
        converter.set_original_model(original_model)
    
    # 智能状态重置：只在必要时重置，避免状态污染但不导致事件顺序问题
    should_reset_state = False
    
    # 检测流开始的标志
    is_stream_start = False
    if isinstance(data, dict):
        # Gemini格式：第一个chunk通常包含responseId但没有finishReason
        if source_format == "gemini" and "responseId" in data and "candidates" in data:
            candidates = data.get("candidates", [])
            if candidates and not candidates[0].get("finishReason"):
                is_stream_start = True
        # OpenAI格式：检查是否是第一个chunk（通常包含role信息）
        elif source_format == "openai" and "choices" in data:
            choices = data.get("choices", [])
            if choices and choices[0].get("delta", {}).get("role") == "assistant":
                is_stream_start = True
        # Anthropic格式：检查message_start事件
        elif source_format == "anthropic" and data.get("type") == "message_start":
            is_stream_start = True
    
    # 检查是否需要重置状态的条件：
    # 1. 转换器实例被复用但模型名称不同
    # 2. 或者是明确的流开始事件
    if hasattr(converter, 'reset_streaming_state') and hasattr(converter, 'original_model'):
        current_model = getattr(converter, 'original_model', None)
        if current_model != original_model:
            should_reset_state = True
            logger.debug(f"Model changed from {current_model} to {original_model}, resetting state")
        elif is_stream_start:
            # 只在明确的流开始时重置
            should_reset_state = True
            logger.debug(f"Stream start detected, resetting state")
    
    if should_reset_state:
        logger.debug(f"Calling reset_streaming_state() on {converter.__class__.__name__}")
        converter.reset_streaming_state()
    else:
        logger.debug(f"Skipping state reset for {converter.__class__.__name__}")
    
    # 根据源格式和目标格式选择相应的流式转换方法
    if target_format == "openai":
        if source_format == "gemini" and hasattr(converter, '_convert_from_gemini_streaming_chunk'):
            return converter._convert_from_gemini_streaming_chunk(data)
        elif source_format == "anthropic" and hasattr(converter, '_convert_from_anthropic_streaming_chunk'):
            return converter._convert_from_anthropic_streaming_chunk(data)
        elif source_format == "responses" and hasattr(converter, '_convert_from_responses_streaming_chunk'):
            return converter._convert_from_responses_streaming_chunk(data)
    elif target_format == "anthropic":
        if source_format == "openai" and hasattr(converter, '_convert_from_openai_streaming_chunk'):
            logger.debug(f"Calling _convert_from_openai_streaming_chunk for {source_format} -> {target_format}")
            return converter._convert_from_openai_streaming_chunk(data)
        elif source_format == "gemini" and hasattr(converter, '_convert_from_gemini_streaming_chunk'):
            logger.debug(f"Calling _convert_from_gemini_streaming_chunk for {source_format} -> {target_format}")
            return converter._convert_from_gemini_streaming_chunk(data)
        elif source_format == "responses" and hasattr(converter, '_convert_from_responses_streaming_chunk'):
            return converter._convert_from_responses_streaming_chunk(data)
    elif target_format == "gemini":
        if source_format == "openai" and hasattr(converter, '_convert_from_openai_streaming_chunk'):
            return converter._convert_from_openai_streaming_chunk(data)
        elif source_format == "anthropic" and hasattr(converter, '_convert_from_anthropic_streaming_chunk'):
            return converter._convert_from_anthropic_streaming_chunk(data)
        elif source_format == "responses" and hasattr(converter, '_convert_from_responses_streaming_chunk'):
            return converter._convert_from_responses_streaming_chunk(data)
    elif target_format == "responses":
        # 处理转换为responses格式的流式转换
        if source_format == "openai" and hasattr(converter, '_convert_from_openai_streaming_chunk'):
            # 首先转换为chat completions格式，然后转换为responses格式
            chat_result = converter._convert_from_openai_streaming_chunk(data)
            if chat_result and chat_result.success:
                # 然后将Chat Completions格式转换为Responses格式
                responses_data = converter._convert_from_chat_completions(chat_result.data)
                return ConversionResult(success=True, data=responses_data)
        elif source_format == "anthropic" and hasattr(converter, '_convert_from_anthropic_streaming_chunk'):
            chat_result = converter._convert_from_anthropic_streaming_chunk(data)
            if chat_result and chat_result.success:
                responses_data = converter._convert_from_chat_completions(chat_result.data)
                return ConversionResult(success=True, data=responses_data)
        elif source_format == "gemini" and hasattr(converter, '_convert_from_gemini_streaming_chunk'):
            chat_result = converter._convert_from_gemini_streaming_chunk(data)
            if chat_result and chat_result.success:
                responses_data = converter._convert_from_chat_completions(chat_result.data)
                return ConversionResult(success=True, data=responses_data)
    
    # 如果没有专门的流式转换方法，检查是否是[DONE]标记或空数据
    if not data or (isinstance(data, dict) and not data) or (isinstance(data, str) and data.strip() == "[DONE]"):
        # 对于[DONE]标记或空数据，直接返回
        return ConversionResult(success=True, data=data)
    
    # 对于其他数据，使用常规的响应转换方法
    return converter.convert_response(data, source_format, target_format)