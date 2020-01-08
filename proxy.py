#!/usr/bin/env python

from socket import socket, AF_INET, SOCK_STREAM, error
import sys
import re
import thread
import select
import time

# global list of bitrates to be accessible for all threads 
# (since those which do not request manifest file have no knowledge of available bitrates)
bitrates = []

def write_to_log(log_file, duration, t_new, t_current, bitrate, web_server_ip, chunkname):
    f = open(log_file, 'a')
    f.write(str(int(time.time())) + ' ' + str(duration) + ' ' + str(t_new) + ' ' + str(t_current) + ' ' + str(bitrate) + ' ' + web_server_ip + ' ' + chunkname + '\n')
    f.close()


def new_thread(browser_connection_socket, log_file, alpha, listen_port, web_server_ip):
    
    # obtain bitrates from manifest file received by some thread
    global bitrates

    # create socket to connect to server web_server_ip
    server_socket = socket(AF_INET, SOCK_STREAM)
    server_socket.bind((fake_ip, 0))
    server_socket.connect((web_server_ip, 8080))

    proxy_manifest_file = ''
    # set initial and new throughput to 10.0 before receiving proxy manifest file 
    t_current = 10.0
    t_new = 10.0
    # set bitrate to 10 before receiving chunks 
    bitrate = 10

    while True:
        
        # receive HTTP request from browser
        browser_req = ''
        try:
            while '\r\n\r\n' not in browser_req:
                browser_req += browser_connection_socket.recv(1)
        except error:
            print('Error receiving request from browser connection socket: ' + str(error))
            browser_connection_socket.close()
            server_socket.close()
            thread.exit()
        
        # reset body len to 0 before receiving HTTP response from server
        #body_len = 0
        # reset req_chunk to False, set to True if requesting a chunk
        req_chunk = False

        # check if request is for manifest file
        if '.f4m' in browser_req:
            # send HTTP request to server, but do not send response to browser
            try:
               server_socket.send(browser_req)
            except error:
                print('Error sending request of proxy manifest file to server: ' + str(error))
                browser_connection_socket.close()
                server_socket.close()
                thread.exit()
            # receive HTTP header of response from server
            server_resp = ''
            try:
                while '\r\n\r\n' not in server_resp:
                    server_resp += server_socket.recv(1)
                # receive HTTP body of response = proxy manifest file from server
                proxy_len = int(re.search('(?<=Content-Length: )\d+', server_resp).group(0))
                recvd = 0
                while recvd < proxy_len:
                    proxy_manifest_file += server_socket.recv(1)
                    recvd += 1
            except error:
                print('Error receiving proxy manifest file from server: ' + str(error))
                browser_connection_socket.close()
                server_socket.close()
                thread.exit()
            # set t_current to lowest bitrate for video
            media_bitrates = re.findall('<media[^>]*bitrate=\"[\d]*', proxy_manifest_file)
            for elt in media_bitrates:
                elt = elt[::-1]
                tmp = re.search('[\d]*', elt).group(0)
                bitrates.append(int(tmp[::-1]))
            bitrates.sort()
            t_current = bitrates[0]
            # modify browser response to be for browser manifest file
            index_point = browser_req.find('.f4m')
            browser_req = browser_req[0:index_point] + '_nolist' + browser_req[index_point:]
        
        # check if request is for a chunk
        chunk_req = re.search('[\d]*Seg[\d]*-Frag[\d]*', browser_req)
        if chunk_req:
            req_chunk = True
            # modify chunk request to be for same chunk, but of appropriate bitrate
            index_point_start = browser_req.find(chunk_req.group(0))
            index_point_end = browser_req.find('Seg')
            # calculate bitrate
            for rate in bitrates:
                if rate * 1.5 <= t_current:
                    bitrate = rate
            if bitrate not in bitrates:
                # force bitrate to be lowest for video
                bitrate = bitrates[0]
            browser_req = browser_req[0:index_point_start] + str(bitrate) + browser_req[index_point_end:]
        
        # store t_s after receiving browser request
        t_s = time.time()

        # forward HTTP request to server
        try:
            server_socket.send(browser_req)
        except error:
            print('Error sending request from browser to server: ' + str(error))
            browser_connection_socket.close()
            server_socket.close()
            thread.exit()

        # receive HTTP header of response from server
        server_resp = ''
        try:
            while '\r\n\r\n' not in server_resp:
                server_resp += server_socket.recv(1)
            # receive HTTP body of response from server (if it exists)
            if 'Content-Length: ' in server_resp:
                body_len = int(re.search('(?<=Content-Length: )\d+', server_resp).group(0))
                recvd = 0
                while recvd < body_len:
                    server_resp += server_socket.recv(1)
                    recvd += 1

        except error:
            print('Error receiving response from server: ' + str(error))
            browser_connection_socket.close()
            server_socket.close()
            thread.exit()

        # store t_f after receiving server response
        t_f = time.time()

        # update estimate of t_current if req_chunk
        if req_chunk:
            # convert body_len from bytes to Kb
            body_len *= 0.008
            t_new = body_len / (t_f - t_s)
            t_current = (alpha * t_new) + ((1 - alpha) * t_current)

        # if request is for chunk, write to log_file
        if chunk_req:
            up_to_chunkname = re.match('GET [\S]*', browser_req).group(0)
            chunkname = up_to_chunkname[4:]
            write_to_log(log_file, t_f - t_s, int(round(t_new)), t_current, bitrate, web_server_ip, chunkname)

        # forward HTTP response to browser
        try:
            browser_connection_socket.send(server_resp)
        except error:
            print('Error sending response from server to browser: ' + str(error))
            browser_connection_socket.close()
            server_socket.close()
            thread.exit()


if __name__ == '__main__':

    # store command line args appropriately
    log_file = sys.argv[1]
    alpha = float(sys.argv[2])
    listen_port = int(sys.argv[3])
    fake_ip = sys.argv[4]
    web_server_ip = sys.argv[5]

    # create listening socket on listen_port for browser requests
    browser_listen_socket = socket(AF_INET, SOCK_STREAM)
    browser_listen_socket.bind(('127.0.0.1', listen_port))
    browser_listen_socket.listen(10)

    while True:
        
        # accept browser request and create browser_connection_socket
        browser_connection_socket, addr = browser_listen_socket.accept()
        thread.start_new_thread(new_thread, (browser_connection_socket, log_file, alpha, listen_port, web_server_ip,)) 
    
