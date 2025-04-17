import json
import aiohttp
import base64

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
    """
    简单的语种检测函数，用于判断文本是英文还是中文
    :param text: 待检测的文本
    :return: 'en' 表示英文，'zh' 表示中文，None 表示不支持的语言
    """
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
    """
    从语音打分结果中解析出 unifyResult 里的 overall 总分
    :param result: 语音打分结果
    :return: overall 总分，如果解析失败则返回 None
    """
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