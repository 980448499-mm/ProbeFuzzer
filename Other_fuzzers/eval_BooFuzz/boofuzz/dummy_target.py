import socket

soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
soc.bind(('localhost', 24301))
soc.listen(1)
output = open('BooFuzz_query_5GC.txt', 'w')
while True:
    conn, _ = soc.accept()
    query = []
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
    for q in query:
        output.write(str(q)+'\n')
    conn.close()
    