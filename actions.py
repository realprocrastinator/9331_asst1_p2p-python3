# actions.py handle all user requests, all messages are sent using TCP/IP protocol
# functions:                      
# 1. peer join                    peer                    
# 2. peer exit gracefully         peer            
# 3. peer exit abruptly           peer        
# 4. store file                   peer
# 5. retrieve file                peer    

from threading import Thread
from msgtype import *
from socket import *
from para import *
from peers import *


host = parameters()["HOST_ADDR"]
PORT_BASE = int(parameters()["PORT_BASE"])


"""
rev from the other peers request, and handle the request 
"""
class Actors(Thread):
    def __init__(self,t_name:str,conn:socket, addr):
        Thread.__init__(self,name = t_name)
        self.conn = conn
        self.addr = addr
        # DEBUG
        self.id = t_name
        # for receiving file
        self.file = None

    def run(self):
        # get the msg from buffer
        msg = self.conn.recv(2048)
        # decode the msg
        msg = message(msg)
        peer_id = msg.header[1]
        action = msg.header[0]    
        # accessing swicth table and handle the event
        
        handler = uargs()["OPTIONS"]
        
        # DEBUG
        # handler = uargs()["HANDLERS" + self.id[-1]]

        # peer join actions, JOIN_UPDATE indicates I'm told to
        # renew my second successor as the joined peer
        if action == signal(header.JOIN_UPDATE):
            print("Successor Change request received")
            # update the second suc of me
            new_suc = byte2int(msg.body)
            
            # DEBUG
            # print("NEW SUC IS:",new_suc)
            
            # disable the ping to sec suc
            for w in handler.workers:
                if w.suc_id == handler.get_suc("second"):
                    w.disable_ping()

            # TODO grab the lock
            # call Eventhandlerto handle update with flag since I'm a predecessor
            handler.suc_update(new_suc,action)
            # display my new successors
            handler.print_successors()

            # enable the ping
            for w in handler.workers:
                if w.suc_id == handler.get_suc("second"):
                    w.disable_ping()
                    w.change_suc(new_suc)
                    w.start()
        
        # PEER_JOIN signal indicates that I need to renew my suc and sec suc
        elif action == signal(header.PEER_JOIN):
            # DEBUG
            # print("I'm peer" + self.id[-1])
            handler.handle_join(peer_id)

        # JOIN_ALLOWED indicates we can update our suc now, dont forget reply finish
        # and call p2pinit()!
        elif action == signal(header.JOIN_ALLOWED):
            print("Join request has been accepted")
            indicator = msg.header[1]
            handler.big_lock.acquire()
            if indicator == 1:
                # set first suc
                handler.peer_ids[0] = byte2int(msg.body)
                print(f"My first successor is Peer {handler.peer_ids[0]}")
            elif indicator == 2:
                # set second suc
                handler.peer_ids[1] = byte2int(msg.body)
                print(f"My Second successor is Peer {handler.peer_ids[1]}")
                # DEBUG
                # print("INFO:" + "indicator:" ,indicator, byte2int(msg.body))
            else:
                # DEBUG
                print("ERROR:" + "indicator:" ,indicator, byte2int(msg.body))
            handler.big_lock.release()

        # peer departure gracefully
        elif action == signal(header.PEER_EXIT):    
            # at this moment we can be a pre or spre
            # we call handle_peer_exit() to handle this event
            
            suc = uargs()["OPTIONS"].get_suc("first")
            ssuc = uargs()["OPTIONS"].get_suc("second")
            
            if msg.header[1] == 0: 
                print(f"Peer {suc} will depart from the network")
                # pre, add suc
                uargs()["OPTIONS"].handle_peer_quit(
                    suc,"first",byte2int(msg.body)
                )
            elif msg.header[1] == 1:
                # pre, add ssuc
                uargs()["OPTIONS"].handle_peer_quit(
                    suc,"second",byte2int(msg.body)
                )
            elif msg.header[1] == 2:
                # spre, add ssuc
                print(f"Peer {ssuc} will depart from the network")
                uargs()["OPTIONS"].handle_peer_quit(
                    ssuc,"second",byte2int(msg.body)
                )
            else:
                print("ERROR: invalid signature")

            # return the ack 
            reply = message()
            reply.setHeader(signal(header.PEER_EXIT_ACK), 0)
            self.conn.send(reply.segment)

        # peer lost
        elif action == signal(header.PEER_LOST):
            loss_peer = byte2int(msg.body)
            relationship = msg.header[1]
            print(uargs()["OPTIONS"].peer.successor)
            if relationship == 0:
                # my suc is lost, send my sscu to my pre to be his ssuc
                suc = handler.get_suc("second")
            else:
                # my pre is lost, I'll become my spre's suc and my suc is his ssuc
                suc = handler.get_suc("first")

            # construct the message
            reply = message()
            sign = 2 # whatever value sent will be his second suc
            # set an signature to indicate the relationship
            reply.setHeader(signal(header.NEW_PEER),2)
            reply.body = int2byte(suc)
            self.conn.send(reply.segment)

        # store file
        elif action == signal(header.FILE_STR):
            file_id = byte2int(msg.body)
            uargs()["OPTIONS"].file_store()

        # request file
        elif action == signal(header.FILE_REQ):
            file_id = byte2int(msg.body)
            requester_id = msg.header[1]
            uargs()["OPTIONS"].handle_file_request (requester_id, file_id)

        # got file response
        elif action == signal(header.FILE_RES):
            # I can start listening to the file 
            uargs()["OPTIONS"].handle_file_waiting(msg.header[1], byte2int(msg.body))
        
        # start receiving file
        elif action == signal(header.SND_FILE):
            uargs()["OPTIONS"].receive_file(msg)

        # I know peer is ready to accept my file
        elif action == signal(header.FILE_RDY):
            requester_id = msg.header[1]
            # add leading zeros eg 4->0004
            filename = str(byte2int(msg.body)).zfill(4)
            # startup the file tr move to TCP start when buffer ready 
            FileSender("FileSender", requester_id, filename +".pdf").start()

        
        # close the TCP socket, open next time when get called again
        self.conn.close()


# a TCP server listening for incoming request
class InfoSer(Thread):
    def __init__(self,t_name):
        Thread.__init__(self,name = t_name)
        self.sock = socket(AF_INET,SOCK_STREAM)
        #for debugging
        try:
            self.myid = int(uargs()["PEER_ID"])
        except Exception:
            self.myid = 2
        self.sock.bind((host,PORT_BASE + self.myid))
        self.sock.listen(5)
    def run(self):
        while True:
            # accept the new incoming connection
            conn,addr = self.sock.accept()
            Actors("Actor" + str(self.myid),conn,addr).start()


# a TCP client for sending 
class InfoClient(Thread):
    def __init__(self, server_id, info_type,
        info_val, requester_id = None):
        Thread.__init__(self)
        # store the passed in values
        self.server_id = server_id
        self.info_type = info_type
        self.info_val = info_val
        if requester_id:
            self.requester_id = requester_id
        else:
            self.requester_id = uargs()["PEER_ID"]

        # setup the socket 
        self.sock = socket(AF_INET, SOCK_STREAM)

    def run(self):
        try:
            self.sock.connect((host, PORT_BASE+self.server_id))
            msg = message()
            msg.setHeader(self.info_type, self.requester_id)
            msg.body = int2byte(self.info_val)

            #DEBUG
            # print("sending..." + f"depart : {byte2int(msg.body)}")
            # send the message 
            self.sock.send(msg.segment)
            # some cases we need to wait response and do callback 
            if self.info_type in [signal(header.PEER_LOST), signal(header.PEER_EXIT)]:
                msg = message(self.sock.recv(1024))
                if msg.header[0] == signal(header.PEER_EXIT_ACK):
                    # exit granted
                    # callback the controller 
                    uargs()["OPTIONS"].quit_allow()
                elif msg.header[0] == signal(header.NEW_PEER):
                    # register new peer
                    # DEBUG
                    print("Assigning new suc.....")
                    uargs()["OPTIONS"].handle_new_suc(
                        "second",byte2int(msg.body)
                    )
        except ConnectionRefusedError:
            # if the suc is not online we just try again
            pass

        # close the connection
        self.sock.close()


# File munipulator
# TODO
# a file sender
class FileSender(Thread):
    def __init__(self,t_name,peer_id, filename):
        Thread.__init__(self,name = t_name)
        
        # set up port, file_name 
        self.requester_port = peer_id + PORT_BASE
        self.filename = filename
        # set up buffer size
        self.size = parameters()["MSG_SIZE"]
        # try open the file if not exsist, then send message file not exsist
        try:
            self.file = open(filename,'rb')
        except FileNotFoundError:
            # TODO send Error msg
            pass
         
        # store the requestor id for later usage
        self.requester_id = peer_id
        # set up socket for TCP
        self.sock = socket(AF_INET,SOCK_STREAM)
        # set up timeout
        self.sock.settimeout(1)
        # connect TCP, established handshake
        self.sock.connect((host, self.requester_port))
        # set up ack#
        self.ack = 0

    def sendfile(self, buf):
        # construct the msg
        msg = message()
        # send the byte stream
        msg.setHeader(signal(header.SND_FILE),self.ack)
        # try to recieve the response, if timeout, send again
        msg.body = buf

        # send the file stream
        self.sock.sendto(
            msg.segment,
            (host,self.requester_port)
        )
    
    def run(self):
        # read the file to the buf
        buf = self.file.read(self.size)
        print("We now start sending the file...")
        # sleep(1)

        sent_length = 0
        # send the whole file
        
        while buf:
            self.sendfile(buf)
            sent_length = len(buf)

            buf = self.file.read(self.size)
        
        # edge case, if the file size % buffer size == 0
        # we send an extra empty msg to notify thats the end of the file
        if sent_length == self.size:
            self.sent(buf)

        # sending over
        print("File is sent....")
            



if __name__ == "__main__":
    # test TCP info client and Rceiver
    from p2p import *
    # test join info
    
    def debug_set(id,suc1 = None, suc2 = None,interval = 30,known = None):
        uargs()["PEER_ID"] = id
        uargs()["FIRST_SUCCESSOR"], uargs()["SECOND_SUCCESSOR"] = suc1,suc2
        uargs()["PING_TINTERVAL"] = interval
        uargs()["OPTIONS"] = EventHandler(uargs()["PEER_ID"],
                                [uargs()["FIRST_SUCCESSOR"], uargs()["SECOND_SUCCESSOR"]],
                                )
        uargs()["HANDLERS" + str(id)] = uargs()["OPTIONS"]
        uargs()["KNOWN_PEER"] = known
        return uargs()["OPTIONS"]


    # intial a peer 1
    p1 = debug_set(1,suc1=2,suc2=3)
    p2 = debug_set(2,suc1=3,suc2=4)
    p3 = debug_set(3,suc1=4,suc2=1)
    p4 = debug_set(4,suc1=1,suc2=2)
    p5 = debug_set(5,known=1)

    p1.p2pinit()

    # initial a peer 2

    p2.p2pinit()

    # initial a peer 3
    
    p3.p2pinit()

    # initial a peer 4
    
    p4.p2pinit()

    # let peer 5 ask 1 to join
    
    p5.p2pjoin()


