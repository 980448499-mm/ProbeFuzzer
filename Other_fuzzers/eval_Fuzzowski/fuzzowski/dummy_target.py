import socket

soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
soc.bind(('localhost', 24302))
soc.listen(1)
output = open('Fuzzowski_query_5GC.txt', 'w')
while True:
    conn, _ = soc.accept()
    query = []
    try:
        while True:
            try:
                data = conn.recv(1024)
                if not data:
                    print('Testcase finished.')
                    break
                else:
                    query.append(data.decode())
                    conn.send('OK'.encode())
            except ConnectionResetError:
                print('Testcase finished.')
                break
        print(query)
        query_str = ""
        for idx, q in enumerate(query):
            if q.startswith("aflnetMessage_"):
                q = q.replace("aflnetMessage_", "")
            q = q.upper()
            query_str = query_str + q
        output.write(query_str+'\n')
        conn.close()
    except:
        continue