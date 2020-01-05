import hashlib
import os
import socket
import threading
import time
from urllib.parse import urlparse

config = {
    'HOST': '127.0.0.1',
    'PORT': 8888,
    'MAX_LENGTH': 4096,
    'TIMEOUT': 200000,
    'CACHE_SIZE': 1000
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
if not os.path.exists(CACHE_DIR):
    os.mkdir(CACHE_DIR)

BLOCKED_HOST = [
    # 'today.hit.edu.cn'
    # 'cs.hit.edu.cn'
    # 'som.hit.edu.cn'
    # 'www.zycg.gov.cn'
    # 'fls.hit.edu.cn'
]

BLOCKED_USER = [
    # '127.0.0.1'
]

FISHING_RULE = {
    'today.hit.edu.cn': 'cs.hit.edu.cn'
    # 'fls.hit.edu.cn':'today.hit.edu.cn'
    # 'today.hit.edu.cn':'som.hit.edu.cn'
}


class ProxyServer:
    def __init__(self, host=config['HOST'], port=config['PORT']):
        self.serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.serverSocket.bind((host, port))
        self.serverSocket.listen(50)
        self.host = host
        self.port = port

    # 开启进程
    def start(self):
        print('Proxy server is listening on {host}:{port}...'.format(host=self.host, port=self.port))
        while True:
            connect, address = self.serverSocket.accept()
            proxyThread = threading.Thread(target=self._proxyThread, args=(connect, address))
            proxyThread.start()

    @staticmethod
    def _proxyThread(connect, address):
        # 处理来自浏览器的请求，提取请求头
        try:
            request = connect.recv(config['MAX_LENGTH'])
            if len(request) == 0:
                return
            http = request.decode('gbk', 'ignore').split('\n')[0]
            # 当访问网站采用https时，请求信息是加密的，以CONNECT开头
            if http.startswith('CONNECT'):
                return
            print(http)

            url = urlparse(http.split()[1])
            print('hostname : ' + url.hostname)
            # 处理域名为空的情况
            if url.hostname is None:
                connect.send(str.encode('HTTP/1.1 404 Not Found\r\n'))
                connect.close()
                return
            # 屏蔽域名
            if isHost(url.hostname):
                connect.send(str.encode('HTTP/1.1 403 Forbidden\r\n'))
                connect.close()
                return
            # 屏蔽用户
            if isUser(address[0]):
                connect.send(str.encode('HTTP/1.1 403 Forbidden\r\n'))
                connect.close()
                return

            # 钓鱼 实现
            replace_hostname = fishing(url.hostname)
            if len(replace_hostname):
                temp = request.decode().replace(url.hostname, replace_hostname)
                request = str.encode(temp)
                url = urlparse(request.decode().split('\r\n')[0].split()[1])

            # 如果port为空 默认访问80端口
            port = 80 if url.port is None else url.port
            # 获取一个md5加密对象
            m = hashlib.md5()
            # 对括号内内容进行加密 加密结果为 m.hexdigest
            m.update(str.encode(url.netloc + url.path))
            filename = os.path.join(CACHE_DIR, m.hexdigest() + '.cached')

            # 如果已经缓存
            if os.path.exists(filename):
                forwardSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                forwardSocket.settimeout(config['TIMEOUT'])
                forwardSocket.connect((url.hostname, port))

                temp = request.decode().split('\n')[0] + '\n'
                # 获取文件的最近修改时间
                t = (time.strptime(time.ctime(os.path.getmtime(filename)), "%a %b %d %H:%M:%S %Y"))
                nowt = (time.strptime(time.ctime(time.time()), "%a %b %d %H:%M:%S %Y"))
                # 添加请求头标签 If-Modified-Since（IMS）
                # If - Modified - Since是标准的HTTP请求头标签，在发送HTTP请求时，
                #   把浏览器端缓存页面的最后修改时间一起发到服务器去，服务器会把这个时间与服务器上实际文件的最后修改时间进行比较。
                # 如果时间一致，那么返回HTTP状态码304（不返回文件内容），客户端接到之后，就直接把本地缓存文件显示到浏览器中。
                # 如果时间不一致，就返回HTTP状态码200和新的文件内容，客户端接到之后，会丢弃旧文件，把新文件缓存起来，并显示到浏览器中。
                temp += 'date: ' + time.strftime('%a, %d %b %Y %H:%M:%S GMT', nowt) + '\n'
                temp += 'If-Modified-Since: ' + time.strftime('%a, %d %b %Y %H:%M:%S GMT', t) + '\n'
                # 添加请求体
                for line in request.decode().split('\n')[1:]:
                    temp += line + '\n'
                # 发送 http
                forwardSocket.sendall(str.encode(temp))

                first = True
                while True:
                    # 从目标服务器接收 response
                    data = forwardSocket.recv(config['MAX_LENGTH'])
                    # 区分第一次返回 response
                    if first:
                        if data.decode('iso-8859-1').split()[1] == '304':
                            # 304 代表缓存没有过期
                            print('Cache hit: {path}'.format(path=url.hostname + url.path))
                            connect.send(open(filename, 'rb').read())
                            break
                        else:
                            # 如果缓存已经过期
                            o = open(filename, 'wb')
                            print('Cache updated: {path}'.format(path=url.hostname + url.path))
                            if len(data) > 0:
                                connect.send(data)
                                # 写入缓存
                                o.write(data)
                            else:
                                break
                            first = False
                    else:
                        o = open(filename, 'ab')
                        if len(data) > 0:
                            connect.send(data)
                            o.write(data)
                        else:
                            break
            else:
                # 如果没有缓存
                print('Cache miss: {path}'.format(path=url.hostname + url.path))
                forwardSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                forwardSocket.settimeout(config['TIMEOUT'])
                forwardSocket.connect((url.hostname, port))
                forwardSocket.sendall(request)

                o = open(filename, 'ab')
                while True:
                    data = forwardSocket.recv(config['MAX_LENGTH'])
                    if len(data) > 0:
                        connect.send(data)
                        o.write(data)
                    else:
                        break
                o.close()

            connect.close()
            forwardSocket.close()
            cacheCounter = 0
            cacheFiles = []
            for file in os.listdir(os.path.join(os.path.dirname(__file__), 'cache')):
                if file.endswith('.cached'):
                    cacheCounter += 1
                    cacheFiles.append(file)
            # 清理缓存
            if cacheCounter > config['CACHE_SIZE']:
                # 按照最近修改时间从大到小排序
                cacheFiles.sort(key=lambda x: -os.path.getmtime(x))
                # 移除修改时间早的缓存文件
                for file in cacheFiles[config['CACHE_SIZE']:]:
                    os.remove(file)
        except Exception as e:
            print(str(e))

    # 关闭代理服务器
    def stop(self):
        mainThread = threading.current_thread()
        for thread in threading.enumerate():
            if thread is mainThread:
                continue
            thread.join()
        self.serverSocket.close()
        exit(0)


# 屏蔽域名
def isHost(host):
    if host in BLOCKED_HOST:
        return True
    return False


# 屏蔽用户
def isUser(user):
    if user in BLOCKED_USER:
        return True
    return False


# 钓鱼 实现
def fishing(host):
    if host in FISHING_RULE:
        print('fishing {0} to {1}'.format(host, FISHING_RULE[host]))
        return FISHING_RULE[host]
    else:
        return ''


if __name__ == '__main__':
    server = ProxyServer()
    server.start()
