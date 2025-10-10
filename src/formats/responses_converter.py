"""
OpenAI Responses格式转换器
处理OpenAI Responses API格式与其他格式之间的转换
"""
from typing import Dict, Any, Optional, List
import json
import copy
import time
import uuid

from .base_converter import BaseConverter, ConversionResult, ConversionError
from .openai_converter import OpenAIConverter


class ResponsesConverter(BaseConverter):
    """OpenAI Responses格式转换器"""

    def __init__(self):
        super().__init__()
        self.original_model = None
        # 使用OpenAI转换器作为基础，因为Responses格式与Chat Completions格式相似
        self.openai_converter = OpenAIConverter()

    def set_original_model(self, model: str):
        """设置原始模型名称"""
        self.original_model = model
        self.openai_converter.set_original_model(model)

    def reset_streaming_state(self):
        """重置所有流式相关的状态变量，避免状态污染"""
        if hasattr(self.openai_converter, 'reset_streaming_state'):
            self.openai_converter.reset_streaming_state()

    def get_supported_formats(self) -> List[str]:
        """获取支持的格式列表"""
        return ["responses", "openai", "anthropic", "gemini"]

    def convert_request(
        self,
        data: Dict[str, Any],
        target_format: str,
        headers: Optional[Dict[str, str]] = None
    ) -> ConversionResult:
        """转换请求格式"""
        try:
            if target_format == "responses":
                # 任何格式到Responses格式，进行直接转换
                return ConversionResult(success=True, data=data)
            else:
                # 从Responses格式到其他格式
                # 首先转换为Chat Completions格式作为中间步骤
                chat_data = self._convert_to_chat_completions(data)

                # 然后转换到目标格式
                if target_format == "openai":
                    return ConversionResult(success=True, data=chat_data)
                elif target_format == "anthropic":
                    return self.openai_converter._convert_to_anthropic_request(chat_data)
                elif target_format == "gemini":
                    return self.openai_converter._convert_to_gemini_request(chat_data)
                else:
                    return ConversionResult(
                        success=False,
                        error=f"Unsupported target format: {target_format}"
                    )
        except Exception as e:
            self.logger.error(f"Failed to convert request to {target_format}: {e}")
            return ConversionResult(success=False, error=str(e))

    def convert_response(
        self,
        data: Dict[str, Any],
        source_format: str,
        target_format: str
    ) -> ConversionResult:
        """转换响应格式"""
        try:
            if target_format == "responses":
                # 任何源格式到Responses格式，进行直接转换
                if source_format == "responses":
                    return ConversionResult(success=True, data=data)
                elif source_format == "openai":
                    # 直接从OpenAI格式转换为Responses格式
                    return self._convert_from_openai_to_responses(data)
                elif source_format == "anthropic":
                    # 直接从Anthropic格式转换为Responses格式
                    return self._convert_from_anthropic_to_responses(data)
                elif source_format == "gemini":
                    # 直接从Gemini格式转换为Responses格式
                    return self._convert_from_gemini_to_responses(data)
                else:
                    return ConversionResult(
                        success=False,
                        error=f"Unsupported source format: {source_format}"
                    )
            else:
                # 从Responses格式到其他格式
                # 首先转换为Chat Completions格式作为中间步骤
                chat_data = self._convert_to_chat_completions(data) if source_format == "responses" else data

                # 然后转换到目标格式
                self.openai_converter.set_original_model(self.original_model)
                return self.openai_converter.convert_response(chat_data, source_format, target_format)

        except Exception as e:
            self.logger.error(f"Failed to convert {source_format} response to {target_format}: {e}")
            return ConversionResult(success=False, error=str(e))

    def _convert_to_chat_completions(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """将Responses格式转换为Chat Completions格式"""
        chat_data = {}

        # 处理输入 (input -> messages)
        if "input" in data:
            input_data = data["input"]
            if isinstance(input_data, list):
                # 如果input已经是messages格式，直接使用
                chat_data["messages"] = input_data
            elif isinstance(input_data, str):
                # 如果input是字符串，转换为messages格式
                chat_data["messages"] = [
                    {"role": "user", "content": input_data}
                ]
            else:
                # 复杂的input格式处理
                chat_data["messages"] = self._convert_input_to_messages(input_data)

        # 处理其他参数
        if "model" in data:
            chat_data["model"] = data["model"]
        if "temperature" in data:
            chat_data["temperature"] = data["temperature"]
        if "max_tokens" in data:
            chat_data["max_tokens"] = data["max_tokens"]
        if "max_output_tokens" in data:
            chat_data["max_tokens"] = data["max_output_tokens"]
        if "stream" in data:
            chat_data["stream"] = data["stream"]
        if "tools" in data:
            chat_data["tools"] = data["tools"]
        if "top_p" in data:
            chat_data["top_p"] = data["top_p"]
        if "stop" in data:
            chat_data["stop"] = data["stop"]

        # 处理reasoning相关的参数
        if "max_completion_tokens" in data:
            chat_data["max_completion_tokens"] = data["max_completion_tokens"]
        if "reasoning_effort" in data:
            chat_data["reasoning_effort"] = data["reasoning_effort"]

        # 处理include参数（用于控制返回内容）
        if "include" in data:
            # 暂时不处理include参数，因为Chat Completions不支持
            pass

        # 处理metadata参数
        if "metadata" in data:
            chat_data["metadata"] = data["metadata"]

        # 处理stream参数
        if "stream" in data:
            chat_data["stream"] = data["stream"]

        return chat_data

    def _convert_from_chat_completions(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """将Chat Completions格式转换为Responses格式"""
        responses_data = {}

        # 生成响应ID
        responses_data["id"] = f"resp_{uuid.uuid4().hex[:24]}"
        responses_data["object"] = "response"
        responses_data["created_at"] = int(time.time())

        # 处理状态
        responses_data["status"] = "completed"

        # 处理输出
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            message = choice.get("message", {})

            output = []

            # 处理文本内容
            content = message.get("content", "")
            if content:
                output.append({
                    "type": "message",
                    "id": f"msg_{uuid.uuid4().hex[:8]}",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": content
                        }
                    ]
                })

            # 处理工具调用
            tool_calls = message.get("tool_calls", [])
            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                output.append({
                    "type": "function_call",
                    "id": tool_call.get("id", ""),
                    "call_id": tool_call.get("id", ""),
                    "name": function.get("name", ""),
                    "arguments": function.get("arguments", "{}")
                })

            responses_data["output"] = output

        # 处理输入（echo input）
        if "messages" in data:
            # 将messages转换为input格式
            responses_data["input"] = self._convert_messages_to_input(data["messages"])

        # 处理使用情况
        if "usage" in data:
            usage = data["usage"]
            responses_data["usage"] = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
            }

        # 处理模型
        if "model" in data:
            responses_data["model"] = data["model"]

        # 处理错误信息
        if "error" in data:
            responses_data["error"] = data["error"]

        # 处理finish_reason
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            finish_reason = choice.get("finish_reason", "stop")
            responses_data["status"] = "completed"
            if finish_reason == "length":
                responses_data["status"] = "completed"
            elif finish_reason == "tool_calls":
                responses_data["status"] = "completed"
            elif finish_reason == "content_filter":
                responses_data["status"] = "canceled"

        return responses_data

    def _convert_input_to_messages(self, input_data: Any) -> List[Dict[str, Any]]:
        """将Responses input转换为Chat Completions messages格式"""
        if isinstance(input_data, list):
            return input_data
        elif isinstance(input_data, str):
            return [{"role": "user", "content": input_data}]
        elif isinstance(input_data, dict):
            # 处理复杂的input格式
            messages = []

            # 检查是否有messages字段
            if "messages" in input_data:
                return input_data["messages"]

            # 检查是否有其他格式的对话
            for role in ["user", "assistant", "system"]:
                if role in input_data:
                    content = input_data[role]
                    if isinstance(content, str):
                        messages.append({"role": role, "content": content})
                    elif isinstance(content, list):
                        messages.append({"role": role, "content": content})

            return messages
        else:
            # 默认处理为字符串
            return [{"role": "user", "content": str(input_data)}]

    def _convert_messages_to_input(self, messages: List[Dict[str, Any]]) -> Any:
        """将Chat Completions messages转换为Responses input格式"""
        if len(messages) == 1:
            message = messages[0]
            if message["role"] == "user" and isinstance(message.get("content"), str):
                # 如果只有一个用户消息且是文本，直接返回字符串
                return message["content"]

        # 否则返回messages格式
        return messages

    def _map_finish_reason_to_status(self, finish_reason: str) -> str:
        """将finish_reason映射到Responses status"""
        mapping = {
            "stop": "completed",
            "length": "completed",
            "tool_calls": "completed",
            "content_filter": "canceled",
            "function_call": "completed",
            "stop_sequence": "completed"
        }
        return mapping.get(finish_reason, "completed")

    def _map_status_to_finish_reason(self, status: str) -> str:
        """将Responses status映射到finish_reason"""
        mapping = {
            "completed": "stop",
            "canceled": "stop",
            "failed": "stop",
            "incomplete": "length"
        }
        return mapping.get(status, "stop")

    def _convert_from_responses_streaming_chunk(self, data: Dict[str, Any]) -> ConversionResult:
        """转换Responses流式响应chunk到目标格式"""
        # Responses API的流式格式相对简单，直接透传给OpenAI格式处理
        # 如果目标格式是responses，直接返回
        return ConversionResult(success=True, data=data)

    # 直接格式转换方法（避免中间Chat Completions步骤）
    def _convert_from_openai_to_responses(self, data: Dict[str, Any]) -> ConversionResult:
        """直接从OpenAI格式转换为Responses格式"""
        try:
            responses_data = {}

            # 生成响应ID
            responses_data["id"] = f"resp_{uuid.uuid4().hex[:24]}"
            responses_data["object"] = "response"
            responses_data["created_at"] = int(time.time())

            # 处理状态
            responses_data["status"] = "completed"

            # 处理输出
            if "choices" in data and data["choices"]:
                choice = data["choices"][0]
                message = choice.get("message", {})

                output = []

                # 处理文本内容
                content = message.get("content", "")
                if content:
                    output.append({
                        "type": "message",
                        "id": f"msg_{uuid.uuid4().hex[:8]}",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": content
                            }
                        ]
                    })

                # 处理工具调用
                tool_calls = message.get("tool_calls", [])
                for tool_call in tool_calls:
                    function = tool_call.get("function", {})
                    output.append({
                        "type": "function_call",
                        "id": tool_call.get("id", ""),
                        "call_id": tool_call.get("id", ""),
                        "name": function.get("name", ""),
                        "arguments": function.get("arguments", "{}")
                    })

                responses_data["output"] = output

            # 处理输入（echo input）
            if "messages" in data:
                # 将messages转换为input格式
                responses_data["input"] = self._convert_messages_to_input(data["messages"])

            # 处理使用情况
            if "usage" in data:
                usage = data["usage"]
                responses_data["usage"] = {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0)
                }

            # 处理模型
            if "model" in data:
                responses_data["model"] = data["model"]

            # 处理错误信息
            if "error" in data:
                responses_data["error"] = data["error"]

            # 处理finish_reason
            if "choices" in data and data["choices"]:
                choice = data["choices"][0]
                finish_reason = choice.get("finish_reason", "stop")
                responses_data["status"] = self._map_finish_reason_to_status(finish_reason)

            return ConversionResult(success=True, data=responses_data)
        except Exception as e:
            self.logger.error(f"Failed to convert from OpenAI to Responses: {e}")
            return ConversionResult(success=False, error=str(e))

    def _convert_from_anthropic_to_responses(self, data: Dict[str, Any]) -> ConversionResult:
        """直接从Anthropic格式转换为Responses格式"""
        try:
            responses_data = {}

            # 生成响应ID
            responses_data["id"] = f"resp_{uuid.uuid4().hex[:24]}"
            responses_data["object"] = "response"
            responses_data["created_at"] = int(time.time())

            # 处理状态
            responses_data["status"] = "completed"

            # 处理输出
            output = []

            # 处理文本内容
            if "content" in data and isinstance(data["content"], list):
                for content_item in data["content"]:
                    if content_item.get("type") == "text":
                        output.append({
                            "type": "message",
                            "id": f"msg_{uuid.uuid4().hex[:8]}",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": content_item.get("text", "")
                                }
                            ]
                        })
                    elif content_item.get("type") == "tool_use":
                        output.append({
                            "type": "function_call",
                            "id": content_item.get("id", ""),
                            "call_id": content_item.get("id", ""),
                            "name": content_item.get("name", ""),
                            "arguments": content_item.get("input", {})
                        })

            responses_data["output"] = output

            # 处理输入（echo input）
            # 在Anthropic格式中，输入通常通过其他方式传递，这里简化处理
            if hasattr(self, '_original_input') and self._original_input:
                responses_data["input"] = self._original_input

            # 处理使用情况
            if "usage" in data:
                usage = data["usage"]
                responses_data["usage"] = {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                }

            # 处理模型
            if "model" in data:
                responses_data["model"] = data["model"]

            # 处理错误信息
            if "error" in data:
                responses_data["error"] = data["error"]

            # 处理停止原因
            if "stop_reason" in data:
                stop_reason = data["stop_reason"]
                if stop_reason == "end_turn":
                    responses_data["status"] = "completed"
                elif stop_reason == "max_tokens":
                    responses_data["status"] = "completed"
                elif stop_reason == "tool_use":
                    responses_data["status"] = "completed"
                else:
                    responses_data["status"] = "completed"

            return ConversionResult(success=True, data=responses_data)
        except Exception as e:
            self.logger.error(f"Failed to convert from Anthropic to Responses: {e}")
            return ConversionResult(success=False, error=str(e))

    def _convert_from_gemini_to_responses(self, data: Dict[str, Any]) -> ConversionResult:
        """直接从Gemini格式转换为Responses格式"""
        try:
            responses_data = {}

            # 生成响应ID
            responses_data["id"] = f"resp_{uuid.uuid4().hex[:24]}"
            responses_data["object"] = "response"
            responses_data["created_at"] = int(time.time())

            # 处理状态
            responses_data["status"] = "completed"

            # 处理输出
            output = []

            # 处理候选回复
            if "candidates" in data and data["candidates"]:
                candidate = data["candidates"][0]

                # 处理文本内容
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "text" in part:
                            output.append({
                                "type": "message",
                                "id": f"msg_{uuid.uuid4().hex[:8]}",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": part["text"]
                                    }
                                ]
                            })
                        elif "functionCall" in part:
                            function_call = part["functionCall"]
                            output.append({
                                "type": "function_call",
                                "id": f"func_{uuid.uuid4().hex[:8]}",
                                "call_id": f"func_{uuid.uuid4().hex[:8]}",
                                "name": function_call.get("name", ""),
                                "arguments": json.dumps(function_call.get("args", {}))
                            })

                # 处理完成原因
                if "finishReason" in candidate:
                    finish_reason = candidate["finishReason"]
                    if finish_reason == "STOP":
                        responses_data["status"] = "completed"
                    elif finish_reason == "MAX_TOKENS":
                        responses_data["status"] = "completed"
                    elif finish_reason == "SAFETY":
                        responses_data["status"] = "canceled"
                    else:
                        responses_data["status"] = "completed"

            responses_data["output"] = output

            # 处理使用情况
            if "usageMetadata" in data:
                usage = data["usageMetadata"]
                responses_data["usage"] = {
                    "prompt_tokens": usage.get("promptTokenCount", 0),
                    "completion_tokens": usage.get("candidatesTokenCount", 0),
                    "total_tokens": usage.get("totalTokenCount", 0)
                }

            # 处理模型
            if "model" in data:
                responses_data["model"] = data["model"]

            # 处理错误信息
            if "error" in data:
                responses_data["error"] = data["error"]

            return ConversionResult(success=True, data=responses_data)
        except Exception as e:
            self.logger.error(f"Failed to convert from Gemini to Responses: {e}")
            return ConversionResult(success=False, error=str(e))