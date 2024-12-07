# CryptoSpy Voice Assistant

A real-time voice assistant that provides cryptocurrency price information through Huddle01's video conferencing platform.

## Features

- Real-time voice interaction through Huddle01
- Cryptocurrency price queries
- End-to-end audio processing with OpenAI
- Support for multiple participants (up to 100)
- Secure communication with end-to-end encryption
 
## Prerequisites

- Python 3.12+
- Huddle01 API Key
- Huddle01 Project ID
- OpenAI API Key

## Environment Variables

Create a `.env` file in the root directory with the following variables:
```
HUDDLE_API_KEY=your_huddle_api_key
HUDDLE_PROJECT_ID=your_huddle_project_id
OPENAI_API_KEY=your_openai_api_key
ROOM_ID=your_room_id 
```
## Installation

1. Clone the repository:
```
git clone https://github.com/yourusername/cryptospy.git
cd cryptospy
```

2. Install dependencies:
```
pip install -r PythonApp/requirements.txt
```

## Usage

1. Start the bot:
```
python PythonApp/test.py
```

2. Join the Huddle01 room through the web interface
3. Ask for cryptocurrency prices using voice commands

## How It Works

The bot uses:
- Huddle01's RTC for real-time audio communication
- OpenAI for speech-to-text and text-to-speech processing
- Custom prompt engineering to handle cryptocurrency price queries
- Event-driven architecture for handling room events and user interactions

## Acknowledgments

- [Huddle01](https://www.huddle01.com/) for the real-time communication platform
- [OpenAI](https://openai.com/) for the AI capabilities
