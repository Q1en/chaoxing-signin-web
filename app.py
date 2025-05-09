import threading
import uuid
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# 全局任务存储
# tasks[task_id] = {
#   'tried': int,          # 已尝试次数
#   'total': int,          # 总码数
#   'current_code': str,   # 最近尝试的手势码
#   'found': bool,         # 是否已找到有效码
#   'success_code': str,   # 找到的有效手势码
#   'state': str           # 'PROGRESS' | 'not_found'
# }
tasks = {}
lock = threading.Lock()

def is_valid_move(path, next_point):
    if next_point in path:
        return False
    if not path:
        return True
    jumps = {
        (1,3):2,(3,1):2,
        (1,7):4,(7,1):4,
        (3,9):6,(9,3):6,
        (7,9):8,(9,7):8,
        (1,9):5,(9,1):5,
        (3,7):5,(7,3):5,
        (2,8):5,(8,2):5,
        (4,6):5,(6,4):5
    }
    last = path[-1]
    if (last, next_point) in jumps and jumps[(last, next_point)] not in path:
        return False
    return True

def generate_gesture_codes():
    codes = []
    def backtrack(path):
        if len(path) >= 4:
            codes.append(''.join(map(str, path)))
        if len(path) == 9:
            return
        for nxt in range(1, 10):
            if is_valid_move(path, nxt):
                backtrack(path + [nxt])
    for start in range(1, 10):
        backtrack([start])
    return codes

# 预先生成全部手势码
gesture_codes = generate_gesture_codes()
TOTAL_CODES = len(gesture_codes)

def worker(task_id, active_id, cookie):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0',
        'Cookie': cookie
    })
    while True:
        with lock:
            st = tasks[task_id]
            # 如果已尝试完且未找到
            if st['tried'] >= st['total'] and not st['found']:
                st['state'] = 'not_found'
                break
            # 如果已经找到，直接退出（保持 state='PROGRESS'）
            if st['found']:
                break

            code = gesture_codes[st['tried']]
            st['current_code'] = code
            st['tried'] += 1

        try:
            url = (
                f"https://mobilelearn.chaoxing.com/widget/sign/pcStuSignController/"
                f"checkSignCode?activeId={active_id}&signCode={code}"
            )
            resp = session.get(url, timeout=8)
            if resp.status_code == 200 and '"result":1' in resp.text:
                with lock:
                    st['found'] = True
                    st['success_code'] = code
                # 发起后续签到请求
                session.get(
                    f"https://mobilelearn.chaoxing.com/widget/sign/pcStuSignController/"
                    f"checkIfValidate?activeId={active_id}"
                )
                session.get(
                    f"https://mobilelearn.chaoxing.com/v2/apis/sign/signIn?"
                    f"activeId={active_id}&signCode={code}"
                )
                break
        except Exception:
            # 网络或超时异常，忽略继续
            pass

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start():
    data = request.get_json()
    active_id = data.get('active_id', '').strip()
    cookie    = data.get('cookie', '').strip()
    if not active_id or not cookie:
        return jsonify({'error': '缺少 active_id 或 cookie'}), 400

    # 创建新任务
    task_id = uuid.uuid4().hex
    tasks[task_id] = {
        'tried': 0,
        'total': TOTAL_CODES,
        'current_code': '',
        'found': False,
        'success_code': '',
        'state': 'PROGRESS'
    }

    # 启动若干线程去爆破
    for _ in range(50):
        t = threading.Thread(target=worker, args=(task_id, active_id, cookie))
        t.daemon = True
        t.start()

    return jsonify({'task_id': task_id})

@app.route('/status/<task_id>')
def status(task_id):
    st = tasks.get(task_id)
    if not st:
        return jsonify({'state': 'not_found'}), 404

    # 如果已找到，保持 state=PROGRESS 让前端读到 found=true
    if st['found']:
        return jsonify({
            'state': 'PROGRESS',
            'progress': 100.0,
            'current_code': st['current_code'],
            'found': True,
            'success_code': st['success_code']
        })

    # 如果尝试完毕还没找到
    if st['state'] == 'not_found':
        return jsonify({'state': 'not_found'})

    # 否则仍在进行中
    return jsonify({
        'state': 'PROGRESS',
        'progress': st['tried'] / st['total'] * 100,
        'current_code': st['current_code'],
        'found': False,
        'success_code': ''
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
