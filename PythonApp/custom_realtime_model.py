import asyncio
import base64
import json
import logging
import uuid
from typing import Literal, Optional, Union

from pydantic import BaseModel

from ai01.agent import Agent, AgentsEvents
from ai01.utils.socket import SocketClient

from ....utils.emitter import EnhancedEventEmitter
from . import _api, _exceptions
from .conversation import Conversation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
import os
import requests

CRYPTO_API_KEY = os.getenv("CRYPTO_API_KEY", "15351a21-8a86-45f4-9c82-c5d4d894eb1b")
CRYPTO_API_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"


class RealTimeModelOptions(BaseModel):
    """
    RealTimeModelOptions is the configuration for the RealTimeModel.
    """

    oai_api_key: str
    """
    OpenAI API Key is the API Key for the OpenAI API.
    """

    model: _api.RealTimeModels = "gpt-4o-realtime-preview"
    """
    Model is the RealTimeModel to be used, defaults to gpt-4o-realtime-preview.
    """

    instructions: str = ""
    """
    Instructions is the Initial Prompt given to the Model.
    """

    modalities: list[_api.Modality] = ["text", "audio"]
    """
    Modalities is the list of things to be used by the Model.
    """

    voice: _api.Voice = "alloy"
    """
    Voice is the of audio voices which will be generated and returned by the Model.
    """

    temperature: float = 0.8
    """
    Temperature is the randomness of the Model, to select the next token.
    """

    input_audio_format: _api.AudioFormat = "pcm16"
    """
    Input Audio Format is the format of the input audio, which is given to the Model.
    """

    output_audio_format: _api.AudioFormat = "pcm16"
    """
    Output Audio Format is the format of the audio, which is returned by the Model.
    """

    max_response_output_tokens: int | Literal["inf"] = 4096
    """
    Max Response Output Tokens is the maximum number of tokens in the response, defaults to 4096.
    """

    base_url: str = "wss://api.openai.com/v1/realtime"
    """
    Base URL is the URL of the RealTime API, defaults to the OpenAI RealTime API.
    """

    tool_choice: _api.ToolChoice = "auto"
    """
    Tools are different other APIs which the Model can access, defaults to auto.
    """

    server_vad_opts: _api.ServerVad = {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 1000,
        "silence_duration_ms": 500,
    }
    """
    Server VAD which means Voice Activity Detection is the configuration for the VAD, to detect the voice activity.
    """

    loop: Optional[asyncio.AbstractEventLoop] = None
    """
    Loop is the Event Loop to be used for the RealTimeModel, defaults to the current Event Loop.
    """

    class Config:
        arbitrary_types_allowed = True


def get_crypto_price(slug: str, currency: str = "USD") -> dict:
    """
    Get the current price of a cryptocurrency.

    Args:
        slug (str): The slug/name of the cryptocurrency (e.g., 'bitcoin', 'ethereum')
        currency (str, optional): The currency to get the price in. Defaults to 'USD'

    Returns:
        dict: A dictionary containing the price data and status
            {
                'success': bool,
                'price': float or None,
                'error': str or None,
                'currency': str
            }
    """
    headers = {"X-CMC_PRO_API_KEY": CRYPTO_API_KEY, "Accept": "application/json"}
    params = {"slug": slug.lower(), "convert": currency.upper()}

    try:
        response = requests.get(CRYPTO_API_URL, headers=headers, params=params)
        response.raise_for_status()

        data = response.json()
        print(data)
        if data.get("status", {}).get("error_code") != 0:
            return {
                "success": False,
                "price": None,
                "error": data.get("status", {}).get("error_message"),
                "currency": currency.upper(),
            }
        price = data["data"][list(data["data"].keys())[-1]]["quote"][currency.upper()][
            "price"
        ]
        return {
            "success": True,
            "price": price,
            "error": None,
            "currency": currency.upper(),
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "price": None,
            "error": f"API request failed: {str(e)}",
            "currency": currency.upper(),
        }
    except KeyError as e:
        return {
            "success": False,
            "price": None,
            "error": "Cryptocurrency or currency not found",
            "currency": currency.upper(),
        }
    except Exception as e:
        return {
            "success": False,
            "price": None,
            "error": f"Unexpected error: {str(e)}",
            "currency": currency.upper(),
        }


# Add the function definition for OpenAI
crypto_price_function = {
    "name": "get_crypto_price",
    "description": "Get the current price of a cryptocurrency in a specified currency",
    "parameters": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "The slug/name of the cryptocurrency (e.g., 'bitcoin', 'ethereum')",
            },
            "currency": {
                "type": "string",
                "description": "The currency to get the price in (e.g., 'USD', 'EUR')",
                "default": "USD",
            },
        },
        "required": ["slug"],
    },
}


def send_message(message: str, sender: str):
    url = "https://7f0d-14-195-142-82.ngrok-free.app/api/messages"

    payload = json.dumps({"text": message, "sender": sender})
    headers = {"Content-Type": "application/json"}

    response = requests.request("POST", url, headers=headers, data=payload)

    print(response.text)


class RealTimeModel(EnhancedEventEmitter):
    def __init__(self, agent: Agent, options: RealTimeModelOptions):
        # Agent is the instance which is interacting with the RealTimeModel.
        self.agent = agent

        self._opts = options
        # Loop is the Event Loop to be used for the RealTimeModel.
        self.loop = options.loop or asyncio.get_event_loop()

        # Socket is the WebSocket connection to the RealTime API.
        self.socket = SocketClient(
            url=f"{self._opts.base_url}?model={self._opts.model}",
            headers={
                "Authorization": f"Bearer {self._opts.oai_api_key}",
                "OpenAI-Beta": "realtime=v1",
            },
            loop=self.loop,
            json=True,
        )

        # Turn Detection is the configuration for the VAD, to detect the voice activity.
        self.turn_detection = options.server_vad_opts

        # Logger for RealTimeModel.
        self._logger = logger.getChild(f"RealTimeModel-{self._opts.model}")

        # Conversation is the Conversations which being are happening with the RealTimeModel.
        self._conversation: Conversation = Conversation(id=str(uuid.uuid4()))

        # Main Task is the Audio Append the RealTimeModel.
        self._main_tsk: Optional[asyncio.Future] = None

    def __str__(self):
        return f"RealTimeModel: {self._opts.model}"

    def __repr__(self):
        return f"RealTimeModel: {self._opts.model}"

    @property
    def conversation(self):
        return self._conversation

    async def connect(self):
        """
        Connects the RealTimeModel to the RealTime API.
        """
        try:
            self._logger.info(
                f"Connecting to OpenAI RealTime Model at {self._opts.base_url}"
            )

            await self.socket.connect()

            asyncio.create_task(self._socket_listen(), name="Socket-Listen")
            print("Session Create")
            await self._session_create()
            print("Session Created")
            self._logger.info("Connected to OpenAI RealTime Model")

            self._main_tsk = asyncio.create_task(
                self._main(), name="RealTimeModel-Main"
            )

        except _exceptions.RealtimeModelNotConnectedError:
            raise

        except Exception as e:
            self._logger.error(f"Error connecting to RealTime API: {e}")
            raise _exceptions.RealtimeModelSocketError()

    async def _session_create(self):
        """
        Session Updated is the Event Handler for the Session Update Event.
        """
        try:
            self._logger.info("Send Session Updated ")

            if not self.socket.connected:
                raise _exceptions.RealtimeModelNotConnectedError()

            opts = self._opts

            session_data: _api.ClientEvent.SessionUpdateData = {
                "instructions": self._opts.instructions,
                "voice": opts.voice,
                "input_audio_format": opts.input_audio_format,
                "input_audio_transcription": {"model": "whisper-1"},
                "max_response_output_tokens": self._opts.max_response_output_tokens,
                "modalities": opts.modalities,
                "temperature": opts.temperature,
                "tools": [
                    _api.FunctionTool(
                        type="function",
                        name="get_crypto_price",
                        description="Get the current price of a cryptocurrency in a specified currency",
                        parameters={
                            "type": "object",
                            "properties": {
                                "slug": {
                                    "type": "string",
                                    "description": "The slug/name of the cryptocurrency (e.g., 'bitcoin', 'ethereum')",
                                },
                                "currency": {
                                    "type": "string",
                                    "description": "The currency to get the price in (e.g., 'USD', 'EUR')",
                                    "default": "USD",
                                },
                            },
                            "required": ["slug"],
                        },
                    )
                ],
                "turn_detection": opts.server_vad_opts,
                "output_audio_format": opts.output_audio_format,
                "tool_choice": opts.tool_choice,
            }

            payload: _api.ClientEvent.SessionUpdate = {
                "session": session_data,
                "type": "session.update",
            }

            await self.socket.send(payload)

        except Exception as e:
            self._logger.error(f"Error Sending Session Update Event: {e}")
            raise

    async def _send_audio_append(self, audio_byte: bytes):
        """
        Send Audio Append is the method to send the Audio Append Event to the RealTime API.
        """
        if not self.socket.connected:
            raise _exceptions.RealtimeModelNotConnectedError()

        pcm_base64 = base64.b64encode(audio_byte).decode("utf-8")

        payload: _api.ClientEvent.InputAudioBufferAppend = {
            "event_id": str(uuid.uuid4()),
            "type": "input_audio_buffer.append",
            "audio": pcm_base64,
        }

        await self.socket.send(payload)

    async def _socket_listen(self):
        """
        Listen to the WebSocket
        """
        try:
            if not self.socket.connected:
                raise _exceptions.RealtimeModelNotConnectedError()

            async for message in self.socket.ws:
                await self._handle_message(message)
        except Exception as e:
            logger.error(f"Error listening to WebSocket: {e}")

            raise _exceptions.RealtimeModelSocketError()

    async def _handle_message(self, message: Union[str, bytes]):
        data = json.loads(message)
        print("DATA\n", data)
        event: _api.ServerEventType = data.get("type", "unknown")

        if event == "session.created":
            self._handle_session_created(data)
        elif event == "error":
            self._handle_error(data)
        elif event == "input_audio_buffer.speech_started":
            self._handle_input_audio_buffer_speech_started(data)
        elif event == "input_audio_buffer.speech_stopped":
            self._handle_input_audio_buffer_speech_stopped(data)
        elif event == "response.audio_transcript.delta":
            self._handle_response_audio_transcript_delta(data)
        elif event == "input_audio_buffer.committed":
            self._handle_input_audio_buffer_speech_committed(data)
        elif event == "conversation.item.input_audio_transcription.completed":
            self._handle_conversation_item_input_audio_transcription_completed(data)
        elif event == "conversation.item.input_audio_transcription.failed":
            self._handle_conversation_item_input_audio_transcription_failed(data)
        elif event == "conversation.item.created":
            self._handle_conversation_item_created(data)
        elif event == "conversation.item.deleted":
            self._handle_conversation_item_deleted(data)
        elif event == "conversation.item.truncated":
            self._handle_conversation_item_truncated(data)
        elif event == "response.created":
            self._handle_response_created(data)
        elif event == "response.output_item.added":
            self._handle_response_output_item_added(data)
        elif event == "response.content_part.added":
            self._handle_response_content_part_added(data)
        elif event == "response.audio.delta":
            self._handle_response_audio_delta(data)
        elif event == "response.audio.done":
            self._handle_response_audio_done(data)
        elif event == "response.text.done":
            self._handle_response_text_done(data)
        elif event == "response.audio_transcript.done":
            self._handle_response_audio_transcript_done(data)
        elif event == "response.content_part.done":
            self._handle_response_content_part_done(data)
        elif event == "response.output_item.done":
            self._handle_response_output_item_done(data)
        elif event == "response.done":
            self._handle_response_done(data)
        elif event == "response.function_call_arguments.done":
            await self._handle_response_function_call_arguments_done(data)

        self._logger.info(f"Unhandled Event: {event}")

    def _handle_response_output_item_done(self, data: dict):
        """
        Response Output Item Done is the Event Handler for the Response Output Item Done Event.
        """
        self._logger.info("Response Output Item Done")

    def _handle_response_content_part_done(self, data: dict):
        """
        Response Content Part Done is the Event Handler for the Response Content Part Done Event.
        """
        self._logger.info("Response Content Part Done")

    def _handle_conversation_item_truncated(self, data: dict):
        """
        Conversation Item Truncated is the Event Handler for the Conversation Item Truncated Event.
        """
        self._logger.info("Conversation Item Truncated")

    def _handle_conversation_item_deleted(self, data: dict):
        """
        Conversation Item Deleted is the Event Handler for the Conversation Item Deleted Event.
        """
        self._logger.info("Conversation Item Deleted")

    def _handle_conversation_item_created(self, data: dict):
        """
        Conversation Item Created is the Event Handler for the Conversation Item Created Event.
        """
        self._logger.info("Conversation Item Created")

    def _handle_session_created(self, data: dict):
        """
        Session Created is the Event Handler for the Session Created Event.
        """
        self._logger.info("Session Created")

    def _handle_error(self, data: dict):
        """
        Error is the Event Handler for the Error Event.
        """
        self._logger.error(f"Error: {data}")

    def _handle_input_audio_buffer_speech_started(self, data: dict):
        """
        Speech Started is the Event Handler for the Speech Started Event.
        """
        self._logger.info("Speech Started")

        if self.agent.audio_track:
            self.agent.audio_track.flush_audio()

            self.agent.emit(AgentsEvents.Listening)

    def _handle_input_audio_buffer_speech_stopped(self, data: dict):
        """
        Speech Stopped is the Event Handler for the Speech Stopped Event.
        """
        self._logger.info("Speech Stopped")

    def _handle_input_audio_buffer_speech_committed(self, data: dict):
        """
        Speech Committed is the Event Handler for the Speech Committed Event.
        """
        self._logger.info("Speech Committed")

    def _handle_conversation_item_input_audio_transcription_completed(self, data: dict):
        """
        Input Audio Transcription Completed is the Event Handler for the Input Audio Transcription Completed Event.
        """
        self._logger.info("Input Audio Transcription Completed")

        send_message(data.get("transcript", "Error in Transcription"), "Human")

    def _handle_conversation_item_input_audio_transcription_failed(self, data: dict):
        """
        Input Audio Transcription Failed is the Event Handler for the Input Audio Transcription Failed Event.
        """
        self._logger.error("Input Audio Transcription Failed")

    def _handle_response_done(self, data: dict):
        """
        Response Done is the Event Handler for the Response Done Event.
        """
        self._logger.info("Response Done")

    def _handle_response_created(self, data: dict):
        """
        Response Created is the Event Handler for the Response Created Event.
        """
        self._logger.info("Response Created")

    def _handle_response_output_item_added(self, data: dict):
        """
        Response Output Item Added is the Event Handler for the Response Output Item Added Event.
        """
        self._logger.info("Response Output Item Added")

    def _handle_response_content_part_added(self, data: dict):
        """
        Response Content Part Added is the Event Handler for the Response Content Part Added Event.
        """
        self._logger.info("Response Content Part Added")

    def _handle_response_audio_delta(self, data: dict):
        """
        Response Audio Delta is the Event Handler for the Response Audio Delta Event.
        """
        self._logger.info("Response Audio Delta")
        print(data)
        base64_audio = data.get("delta")

        if base64_audio and self.agent.audio_track:
            self.agent.emit(AgentsEvents.Speaking)
            self.agent.audio_track.enqueue_audio(base64_audio=base64_audio)

    def _handle_response_audio_transcript_delta(self, data: dict):
        """
        Response Audio Transcript Delta is the Event Handler for the Response Audio Transcript Delta Event.
        """
        self._logger.info("Response Audio Transcript Delta")

    def _handle_response_audio_done(self, data: dict):
        """
        Response Audio Done is the Event Handler for the Response Audio Done Event.
        """
        self._logger.info("Response Audio Done")

    def _handle_response_text_done(self, data: dict):
        """
        Response Text Done is the Event Handler for the Response Text Done Event.
        """
        self._logger.info("Response Text Done")

    def _handle_response_audio_transcript_done(self, data: dict):
        """
        Response Audio Transcript Done is the Event Handler for the Response Audio Transcript Done Event.
        """
        self._logger.info("Response Audio Transcript Done")
        send_message(data.get("transcript", "Error in Transcription"), "Agent")

    async def _handle_response_function_call_arguments_done(self, data: dict):
        """
        Response function call.
        """
        print("\n\n\n", data, "\n\n\n\n")
        available_functions = {
            "get_crypto_price": get_crypto_price,
        }
        function_name = data.get("name")
        fuction_to_call = available_functions[function_name]
        output = fuction_to_call(
            json.loads(data.get("arguments")).get("slug"),
            json.loads(data.get("arguments")).get("currency", "USD"),
        )
        api_payload: _api.ClientEvent.FunctionCallOutputItemCreate = {
            "type": "function_call_output",
            "call_id": data.get("call_id"),
            "output": json.dumps(output),
        }
        conv_item = _api.ClientEvent.ConversationItemCreateContent = api_payload
        payload: _api.ClientEvent.ConversationItemCreate = {
            "type": "conversation.item.create",
            "item": conv_item,
        }
        await self.socket.send(payload)
        body_data: _api.ClientEvent.ResponseCreateData = {
            "modalities": ["audio", "text"],
            "instructions": "provide an response to the request based on the information from the tool call",
            "voice": "alloy",
            "output_audio_format": "pcm16",
            "tools": [],
            "tool_choice": "auto",
            "temperature": 0.7,
            "max_output_tokens": "inf",
        }
        resp_body = _api.ClientEvent.ResponseCreate = {
            "type": "response.create",
            "response": body_data,
        }
        await self.socket.send(resp_body)
        self._logger.info("Response Function Call Done")

    async def _main(self):
        if not self.socket.connected:
            raise _exceptions.RealtimeModelNotConnectedError()

        try:

            async def handle_audio_chunk():
                while True:
                    if not self.conversation.active:
                        await asyncio.sleep(0.01)
                        continue

                    audio_chunk = self.conversation.recv()

                    if audio_chunk is None:
                        await asyncio.sleep(0.01)
                        continue

                    await self._send_audio_append(audio_chunk)

            self._main_tsk = asyncio.create_task(
                handle_audio_chunk(), name="RealTimeModel-AudioAppend"
            )
        except Exception as e:
            self._logger.error(f"Error in Main Loop: {e}")
