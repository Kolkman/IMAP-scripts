import getpass
import imaplib
import os
import re
import sys
import email.message
import datetime
import keyring

from email.parser import HeaderParser
# See http://pymotw.com/2/imaplib/xb
__author__ = 'Olaf Kolkman based on http://pymotw.com/2/imaplib/xb (link broken)'
__license__ = 'BSD 3 clause License'





def open_connection_to_IMAPServer(hostname,username):
    """Opens SSL Connection to an IMAP Server and returns a imaplib.IMAP4_SSL object

    hostename: hostname to connect to
    username: username
    password: password
    """

    password=keyring.get_password('archive_mail('+hostname+')',username)

    if not password:
        print (f"Enter password for {username}@{hostname}")
        password = getpass.getpass()
        keyring.set_password('archive_mail('+hostname+')',username,password)
    try:
        connection = imaplib.IMAP4_SSL(hostname,'993')
        connection.login(username, password)
    except imaplib.IMAP4.error as e:
        myre=re.compile('^\s*\[AUTHENTICATIONFAILED\].*')
        if (myre.match(e.message)):
            print (f"Authentication denied for {username}")
            keyring.delete_password('archive_mail('+hostname+')',username)
            connection=open_connection_to_IMAPServer(hostname,username) #DEEP Recursion
        else:
            print (f"Could not connect to IMAP server: {e.message}")
            exit(0)
    return connection


def parse_list_response(line):
    _list_response_pattern = re.compile(r'\((?P<flags>.*?)\) "(?P<delimiter>.*)" (?P<name>.*)')
    flags, delimiter, mailbox_name = _list_response_pattern.match(line).groups()
    mailbox_name = mailbox_name.strip('"')
    return (flags, delimiter, mailbox_name)







class MessageContainer(email.message.Message):
    """MessageContainer: A helper class for processing information from messages

    uid: The uid of the message
    header: Key-value-pair of header
    """
    def get_datetime(self):
        """Returns the time (float) associated with the Message in the Container"""
        return self.datetime

    def get_uid(self):
        """Returns the uid associated with the Message in the Container"""
        return self.uid

    def __init__(self, uid, headerstr):
        """Initiallize

        uid: a string with the UID
        headerstr: a string containing a header
        """
        # Trial and error object copy. NEEDS REVIEW
        parser=email.parser.HeaderParser()
        msg=parser.parsestr(headerstr.decode('utf-8'))
        self.__dict__=msg.__dict__
        self.uid=uid.decode('utf-8')
        date=None
        date_str=self.get("Date")
        if date_str:
            date_tuple=email.utils.parsedate_tz(date_str)
            if date_tuple:
                date=datetime.datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
        self.datetime= date
        self.moved=''
        
    def __repr__(self):
        """Returns as string representing the object by uid and email.message instance"""
        return 'MessageContainer (uid=%s %s)' % (self.uid,str(self.datetime))






#Shamelessly copied from
# http://stackoverflow.com/questions/3041986/python-command-line-yes-no-input

def query_yes_no(question, default="no"):
    """Ask a yes/no question via input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is one of "yes" or "no".
    """
    valid = {"yes":True,   "y":True,  "ye":True,
             "no":False,     "n":False}
    if default == None:
        prompt = " [y/N] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "\
                             "(or 'y' or 'n').\n")







class ImapNode():
    """ImapNode

    children: array of ImapNode Children
    parent: parent of the node
    name: name of the node
    number_of_messages
    """

    def add_path(self,fullname,flags=[],number_of_messages=0):
        path=fullname.split(self.delimiter)
        childname=path.pop(0)
        child=None
        if self.children:
            for c in self.children:
                if c.name == childname:
                    if path:
                        c.add_path(self.delimiter.join(path),flags,number_of_messages)
                        child=c
                        break
        if not child:    
                 child=ImapNode(name=childname,parent=self,delimiter=self.delimiter,depth=self.depth+1, flags=flags, number_of_messages=number_of_messages)
                 self.children.append(child)
                 if path:
                     child.add_path(self.delimiter.join(path),flags,number_of_messages)
        return child

        
    def set_delimiter(self,delimiter):
        self.delimiter=delimiter

    def recursive_print(self):
        print (self)
        for i in self.children:
            i.recursive_print()
        return


    def __init__(self, name='', parent=None, delimiter='/', depth=0, flags=[],number_of_messages=0):
        """Initiallize

        name: name of the Node
        parent: parent object defaults to None
        delimiter: delimiter used by Imap (default '/')
        """
        
        self.name=name
        self.parent=parent
        self.children=[]
        self.number_of_messages= number_of_messages
        self.delimiter=delimiter
        self.depth=depth
        self.flags=flags
        parentname=""
        if parent:
            parentname=parent.name
            pass
        
        #print (f'Initialized {parentname} -> {self.name} ({" ".join(flags)})')


    def delete_empty_branches(self, connection):
        """delete the node  and all its child nodes if there are no messages in the branch

        """
        allempty=True
        for i in self.children:
            if i.delete_empty_branches(connection):
                allempty=False
        if not allempty:
            return True
        if self.number_of_messages:
            return True
        if query_yes_no ("Delete mailbox %s" % self.path(),default='yes' ):
            print(f"DELETING {self.path()}")
            typ,resp= connection.delete(self.path())
            #pprint (typ)
            if typ!='OK':
                print ("Failed to delete directory")
                print (resp)

    def child_mailboxes(self):
        """Returns an array with the path to the mailboxes that contain any messages
        """
        mailboxes=[]
        if self.children:
            for i in self.children:
                mailboxes= mailboxes + i.child_mailboxes()
        elif "NoInferiors" in self.flags or "HasNoChildren" in self.flags:
            if self.number_of_messages:
                mailboxes.append(self.path())
        else:
            print (f"Empty mailbox {self.path()}")
        return mailboxes
        

    def findnode(self,fullname):
        "Returns an ImapMode instance that is located at fullname, or None"""
        path=fullname.split(self.delimiter)
        if path:
            childname=path.pop(0)
            # We need to go into depth
            for c in self.children:
                if c.name == childname:
                    node=c.findnode(self.delimiter.join(path))
                    if node:
                        return node
                    else:
                        return c
        else:
            return None
            
    def path(self):
        path=""
        if self.parent and self.parent.path():
            path=self.parent.path() + self.delimiter + self.name
        else:
            path=self.name
        return path
        
    def __repr__(self):
        #def __repr__(self):
        """Returns as string representing the object by uid and email.message instance"""
        if self.parent:
            parent_name=self.parent.name
        else:
            parent_name=None

        children=''    
        for child in self.children:
            children=children +" " + child.name
        other=" ".join(self.flags)

        if "HasChildren" in self.flags:
            other= "D"
        elif "NoInferiors" in self.flags or "HasNoChildren" in self.flags:
            other = "%d" % self.number_of_messages
            
        return ('%s  [%s] : %s' % (self.path(),  children, other))
                                    


