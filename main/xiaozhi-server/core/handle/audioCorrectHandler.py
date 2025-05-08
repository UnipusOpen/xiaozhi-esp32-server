import json
import aiohttp
import base64
import wave
import numpy as np
import opuslib

def get_cmd_correct_status(conn, text):
    start_prompts = conn.config.get('AUDIO_CORRECT', {}).get('start_prompt', [])
    if text in start_prompts:
        conn.cmd_correct_status = True
        return True

    end_prompts = conn.config.get('AUDIO_CORRECT', {}).get('end_prompt', [])
    if text in end_prompts:
        conn.cmd_correct_status = False
        conn.last_text = ''
        return False
    return getattr(conn, 'cmd_correct_status', False)

def simple_lang_detect(text):
    chinese_count = 0
    english_count = 0

    for char in text:
        # 判断是否为中文字符
        if '\u4e00' <= char <= '\u9fff':
            chinese_count += 1
        # 判断是否为英文字符
        elif char.isalpha():
            english_count += 1

    if chinese_count > 0 and chinese_count >= english_count:
        return 'zh'
    elif english_count > 0 and english_count >= chinese_count:
        return 'en'
    return None

def parse_overall_score(result):
    try:
        unify_result_str = result.get('data', {}).get('unifyResult')
        if unify_result_str is None:
            return None
        unify_result = json.loads(unify_result_str)
        return unify_result.get('overall')
    except (json.JSONDecodeError, AttributeError):
        return None

async def audio_correct(conn, text, auto):
    auto_correct_enabled = conn.config["AUDIO_CORRECT"]["auto_enabled"]
    cmd_correct_enabled = conn.config["AUDIO_CORRECT"]["cmd_enabled"]
    if not auto_correct_enabled and not cmd_correct_enabled:
        print("语音测评功能未启用，不进行测评!")
        return None
    sync_audio_correct_url = conn.config["AUDIO_CORRECT"]["url"]

    real_text = ''
    if auto:
        real_text = text
        if not conn.asr_audio or not real_text:
            print("自动口语测评音频数据或参考文本为空，不进行测评!")
            return None
    else:
        real_text = getattr(conn, 'last_text', '')
        if not conn.asr_audio or not real_text:
            print("交互口语测评音频数据或上次文本为空，不进行测评!")
            return None

    save_opus_to_wav(conn.asr_audio, "D:\tmp\test.wav", 16000, 1)

    try:
        lang = simple_lang_detect(real_text)
        if lang == 'en':
            lang_param = 1
        elif lang == 'zh':
            lang_param = 9
            print("暂不支持中文，不进行测评。")
            return None
        else:
            print("不支持的语言，不进行测评。")
            return None
    except Exception as e:
        print(f"语言检测出错: {e}")
        return None

    async with aiohttp.ClientSession() as session:
        headers = {
            'Content-Type': 'application/json',
            'auth': conn.config["AUDIO_CORRECT"]["auth"]
        }

        # 处理 conn.asr_audio 为列表的情况
        if isinstance(conn.asr_audio, list):
            # 如果列表元素是字符串，先拼接成字符串再编码为字节
            if all(isinstance(item, str) for item in conn.asr_audio):
                audio_bytes = ''.join(conn.asr_audio).encode('utf-8')
            # 如果列表元素是字节类型，合并字节
            elif all(isinstance(item, bytes) for item in conn.asr_audio):
                audio_bytes = b''.join(conn.asr_audio)
            else:
                print("conn.asr_audio 列表元素类型不支持")
                return None
        else:
            audio_bytes = conn.asr_audio

        data = {
            "lang": lang_param,
            "engine": "3",
            "userId": "uid",
            "quesType": 5,
            "requestJson": json.dumps({"refText": real_text, "3": {"audioType": "wav"}}),
            "audioBytes": base64.b64encode(audio_bytes).decode('utf-8')
        }

        async with session.post(sync_audio_correct_url, json=data, headers=headers) as response:
            if response.status == 200:
                result = await response.json()
                print(f"语音打分结果: {result}")
                overall_score = parse_overall_score(result)
                return overall_score
            else:
                print(f"请求失败，状态码: {response.status}")
                return None


def save_opus_to_wav(opus_data, output_file, sample_rate=16000, channels=1):
    """
    将Opus音频数据解码并保存为WAV文件
    
    参数:
    opus_data: 二进制Opus数据
    output_file: 输出WAV文件路径
    sample_rate: 采样率，默认16kHz
    channels: 声道数，默认单声道
    """
    try:
        # 确保opus_data是字节类型
        if isinstance(opus_data, list):
            if all(isinstance(item, str) for item in opus_data):
                opus_data = ''.join(opus_data).encode('utf-8')
            elif all(isinstance(item, bytes) for item in opus_data):
                opus_data = b''.join(opus_data)
            else:
                print("opus_data 列表元素类型不支持")
                return False
        elif isinstance(opus_data, str):
            opus_data = opus_data.encode('utf-8')
        elif not isinstance(opus_data, bytes):
            print("opus_data 类型不支持，需要字节类型")
            return False

        # 检查opus_data是否为空
        if len(opus_data) == 0:
            print("Opus数据为空，无法解码")
            return False

        # 初始化解码器
        decoder = opuslib.Decoder(sample_rate, channels)
        
        # 定义frame_size，这里假设一个常见的值，可根据实际情况调整
        frame_size = 960
        
        # 分帧解码
        pcm_data_list = []
        offset = 0
        while offset < len(opus_data):
            try:
                # 尝试找到一个可能的帧
                max_frame_size = min(len(opus_data) - offset, 4000)  # Opus帧最大长度通常不超过4000字节
                for frame_len in range(max_frame_size, 0, -1):
                    try:
                        frame = opus_data[offset:offset + frame_len]
                        pcm_frame = decoder.decode(frame, frame_size)
                        pcm_data_list.append(pcm_frame)
                        offset += frame_len
                        break
                    except opuslib.OpusError:
                        continue
                else:
                    print("无法找到有效的Opus帧，数据可能损坏")
                    return False
            except opuslib.OpusError as opus_error:
                print(f"Opus解码出错: {opus_error}")
                return False

        # 合并所有PCM数据
        pcm_data = b''.join(pcm_data_list)
        
        # 检查解码后的PCM数据是否为空
        if len(pcm_data) == 0:
            print("解码后的PCM数据为空，无法保存为WAV文件")
            return False

        # 将PCM数据转换为numpy数组
        pcm_array = np.frombuffer(pcm_data, dtype=np.int16)
        
        # 创建WAV文件
        with wave.open(output_file, 'wb') as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)  # 16位音频
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_array.tobytes())
            
        print(f"已成功保存WAV文件: {output_file}")
        return True
    except Exception as e:
        print(f"保存WAV文件失败: {e}")
        return False