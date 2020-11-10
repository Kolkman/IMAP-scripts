#!/usr/bin/env python
""" archive_mail

Imap client script that refiles mails from an Imap folder to other folders based
on a particular rule set and a few heuristics


"""

from OMK_imap_tools_lib import *
from pprint import pprint
from progressbar import *     #pip install progressbar    
import yaml    #pip install pyyaml
import logging
import re
from time import (mktime)
from datetime import datetime, timedelta
import argparse
import keyring   # pip install keyring
from cerberus import Validator #pip install cerberus

#logging.basicConfig(level = logging.DEBUG, filename="tmp.log")

#imaplib.Debug  =  4

__author__ = 'Olaf Kolkman based on http://pymotw.com/2/imaplib/xb (link broken)'
__license__ = 'BSD 3 clause License'



################
# Function defs
################




def _match_against_regex(mc,regex_array):
    # mc: the message container
    # the regex_array datastructure:
    #    Regexps:
    #           type: list
    #           schema:
    #             type: dict
    #             schema:
    #              header:
    #                type: string
    #              regex:
    #                type: string
    
    matches = 0
    expected_matches = len (regex_array)
    logging.debug(f"Match against Regex: {expected_matches} matches expected")
    
    for i in list(regex_array):
        header=i["header"]
        regex=i["regex"]
        try:
            try:
                logging.debug(f'{header}: {mc.get(header)}    c:{regex}')
            except UnicodeDecodeError:
                logging.debug(f'h {header}: c: UNICODE ERROR')
                
            if not regex and not mc.get_all(header):
                logging.debug(f"found match for {header}: NOT IN HEADER")
                matches += 1
                continue

            elif  regex and mc.get_all(header):
                for h in mc.get_all(header):    
                    if re.match(regex,h,re.DOTALL)!=None:
                        logging.debug(f"found match for {header}: {mc.get(h)}")
                        matches += 1
                        logging.debug(f"expected {expected_matches}, actual {matches}")
                        continue
            else:
                pass
            

        except (re.error, e):
            print (f"Error in regexp against {header} : {regex}")
            print (e)
            exit (0) 
        
    logging.debug(f"After all matches I expected {expected_matches}, and got actual {matches}")
    
    if expected_matches == matches:
        return True
    else:
        return False
pass
#END FUNCTION



def _create_rule_based_destination(mc,rule):
    dest_year=mc.get_datetime().year
    dest_month=mc.get_datetime().month
    if 1 <= dest_month <=3 :
        dest_quarter="Q1"
    if 4 <= dest_month <=6 :
        dest_quarter="Q2"
    if 7 <= dest_month <=9 :
        dest_quarter="Q3"
    if 10 <= dest_month <=12 :
        dest_quarter="Q4"
        
    destination_path_elements=[]
    destination_path_elements.extend(rule["DestinationArchive"].split("/"))

    policy=rule["DestinationArchivePolicy"]
    if  policy == "ByYear":
        destination_path_elements.append("%4d"%dest_year)
    elif  policy == "ByQuarter":
        destination_path_elements.extend(["%4d"%dest_year, dest_quarter])
    elif  policy == "ByMonth":
        destination_path_elements.extend(["%4d"%dest_year, "%2d"%dest_month])
    else:
        # Treat as Flat
        pass
    logging.debug("Destination set to " + "/".join(destination_path_elements)) 
    return (destination_path_elements)
pass
            
##########################################################3


##########
#  Parse commandLine
parser = argparse.ArgumentParser()
parser.add_argument("YAMLconfig",help="name of YAML configuration file")
parser.add_argument("-b", "--breakpoint", type=int, default=0,
                    help="break after scanning BREAK messages")
parser.add_argument("-n", "--nomove",  action="store_true", default=False,
                    help="do all the work, except moving the messages")

parser.add_argument("-m", "--mailbox", 
                    help="Use this mailbox instead of the configured one")
args = parser.parse_args()

############################
# Load and test the config file

try:
    with open(args.YAMLconfig, 'rb') as fp:
        configuration_data = yaml.load(fp,Loader=yaml.SafeLoader)

    logging.debug(f"Opened Configurationa File: {args.YAMLconfig}")
except IOError:
    print (f"Error: Configuration file {args.YAMLconfig} cannot be opened")
    exit(0)
except ValueError as e:
    print (f"Error: Check your YAML config file for errors:\n      {e}")
    exit(0)
pass

#pprint(configuration_data)


raw_schema_yaml ="""
name:
    type: string
mailbox:
    type: string
List-Id-Destination:
    type: string
Date-Destination:
    type: string
OlderThen:
    type: integer
Unknown-Date-Destination:
    type: string
connection:
    type: dict
    schema:
      server:
        type: string
      user:
        type: string
ArchiveRules:
    type: list
    required: true
    schema:
        type: dict
        required: true
        schema:
         name:
           type: string
         Priority:
           type: number
         DestinationArchive:
           type: string
           regex: ^([a-zA-Z0-9_-]|\.)+(/([a-zA-Z0-9_-]|\.)+)*$
         DestinationArchivePolicy:
           type: string
           allowed: 
             - 'Flat'
             -  ByMonth'
             - 'ByYear'
             - 'ByQuarter'
         Regexps:
           type: list
           schema:
             type: dict
             schema:
              header:
                type: string
              regex:
                type: string

"""

schema = yaml.load(raw_schema_yaml,Loader=yaml.SafeLoader)

##pprint (schema)

v = Validator(schema)

if not v.validate(configuration_data):
    print(f"Error: Configuration file {args.YAMLconfig} does not comply to the scheme")
    print(v.errors)
    exit(0)





for rule in list(configuration_data['ArchiveRules']):
    for p in rule['DestinationArchive']:
        try:
            if re.search('\s',p):
                raise Exception (
                    "Rule has Destination with space\n" + 
                    "Look for string \"%s\" in %s" % (p, args.YAMLconfig) )
        except Exception as e:
            print (f"\nERROR Parsing config\n{e}\n\n")
            exit(0)



############################
# Connect to the server
server   = configuration_data["connection"]["server"]
username = configuration_data["connection"]['user']


mailbox  = configuration_data['mailbox']
if args.mailbox:
    mailbox=args.mailbox

movethem=not args.nomove

RootNode=ImapNode("")
print (f"Connecting to: {server}")
c = open_connection_to_IMAPServer(server,username)

try: # If anything fails close the connection gracefully
    typ, data = c.list(mailbox)
    if typ != "OK":
        raise Exception("Could not read %s"% mailbox)
    if not data[0]:
        print (f"Nonexistent mailbox: {mailbox}")
        exit(0)

    # Set up Progress Bar
    widgets = ['Scanning structure ', 
               SimpleProgress(), ' ', 
               Bar(marker='=',left='[',right=']'),
               ' ', ETA(), ' '] #see docs for other options
     
    pbar  =  ProgressBar(maxval = len(data),widgets = widgets)
    pbar.start()        
    #scann the whole lot.
    matchfound=0
    for i in range(len(data)):
        line=data[i].decode('utf-8')
        logging.debug (f"line: {line}")
        pbar.update(i)
        #print(line)
        pflags, pdelimiter, pmailbox= parse_list_response(line)
        RootNode.set_delimiter(pdelimiter)
        f=re.compile("\w+")
        theflags=f.findall(pflags)
        logging.info (f"evaluating {pmailbox} against {mailbox} delimiter: {pdelimiter}")
        # We only want the exact mailbox, or its children
        mre=re.compile("^"+mailbox+"("+pdelimiter+".*)?$")
        if not mre.match(pmailbox):
            continue
        else:
            matchfound=1

        n=0
        if "NoInferiors" in theflags or "HasNoChildren" in theflags:
            typ, mb = c.select(pmailbox,readonly=True)
            if typ != "OK":
                raise Exception("Could not read %s"%pmailbox)
            uidval = c.response('UIDVALIDITY')
            typ, msg_ids = c.uid('search',None, 'ALL')
            n=len(msg_ids[0].split())
            c.close()
        RootNode.add_path(pmailbox, flags= theflags, number_of_messages=n)


    pbar.finish()
    if not matchfound:
        print (f"Mailbox {mailbox} doesn't exist")
        exit(0)
        
    node=RootNode.findnode(mailbox)
    
    for box in node.child_mailboxes():
        msglist = []
        typ, mb = c.select(box,readonly=False)
        if typ != "OK":
            raise Exception("Could not select %s (%s)"% (mailbox,typ))
        if  int(mb[0]) == 0:
            raise Exception("Nothing")
        uidval = c.response('UIDVALIDITY')

        # Get all message UIDs
        typ, msg_ids = c.uid('search',None, 'ALL')
        msgarray = (msg_ids[0].split())


        # Set up Progress Bar
        widgets = ['Scanning %s: ' % box, 
                   SimpleProgress(), ' ', 
                   Bar(marker='=',left='[',right=']'),
                   ' ', ETA(), ' '] #see docs for other options
     
        pbar  =  ProgressBar(maxval = len(msgarray),widgets = widgets)
        
        pbar.start()        

        # Scann all messages in the box and create an arracy with
        # MessageContainer objects to work on later.
        for index, msguid in enumerate(msgarray):
            if args.breakpoint >0:
                if index == args.breakpoint:
                    break   #USE WHILE DEVELOPING
            typ, msg_data = c.uid('fetch',msguid,'(BODY.PEEK[HEADER] ENVELOPE)')
            # DATA Structure in MSG_DATA
            # [('1 (UID 127055 BODY[HEADER] {1669}', 'Return-Path: <kassa@
            pbar.update(index)
            hdr = msg_data[0][1]
            mc=MessageContainer(msguid,hdr);
            msglist.append(mc)
            pass
        pbar.finish()
     
        # Sort the lot, just for fun
        try:
            msglist.sort(key=lambda mc: mc.get_datetime())
        except:
            pass #just don't bork over it.
         
        # Initialize a Destination dict
        # It is going to contain the name of a destination folders as key
        # and message message container references as values
        destinations = {}

        # Initialize a hints dict
        # It will contain List-IDs that can be filtered on
        # Those can be used to adapt the configuration
        hints={}


        widgets = ['Matching rules: ', 
                   Percentage(), ' ', 
                   Bar(marker='=',left='[',right=']'),
                   ' ', ETA(), ' '] #see docs for other options
        
        pbar  =  ProgressBar(maxval = len(msglist),widgets = widgets)
        pbar.start()        
        i=0


        ############################
        #
        # Scan all mails by going through the list of message container objects
        for mc in msglist:
            pbar.update(i)
            i+=1

            logging.debug( "------------------------------------" )
            logging.debug(f'Assessing {mc.get_uid()}: \"{mc.get("Subject")}\" ({mc.get("Date")})')

            try: #Sometimes date parsing fails
                if  (( datetime.now() -  mc.get_datetime() ) <
                     timedelta (days = configuration_data["OlderThen"])):
                    logging.debug( f'Message is younger than {configuration_data["OlderThen"]} ({mc.get("Date")})')
                    continue
            except TypeError: 
                print ("datetime failure")
##                pprint (mc)
                
                destinations[configuration_data['Unknown-Date-Destination']]= [ configuration_data['Unknown-Date-Destination'].split(node.delimiter), [(mc.get_uid())]]
                mc.moved= configuration_data['Unknown-Date-Destination']
                continue
                



            logging.debug("processing UID %s"%mc.get_uid())
            #
            # Parse all Rules
            if not mc.moved:             
                PrioritizedRules = sorted(configuration_data['ArchiveRules'], key=lambda x: x['Priority'] , reverse=True)
##                pprint (PrioritizedRules)
                for rule in PrioritizedRules:
                    destination_path_elements = []
                    if _match_against_regex(mc,rule["Regexps"]):
                        logging.debug("creating rule %s"% rule) 
                        destination_path_elements=_create_rule_based_destination(mc,rule);
                    if destination_path_elements: # no rulxse matched. Just don't archive
                        destination_path= node.delimiter.join(destination_path_elements)
                        if re.match(r"\s", destination_path):
                            raise Exception(
                                "Better review the destination, it contains a space: %s" %
                                destination_path)
                        
                        if re.match("^"+box+node.delimiter, destination_path):
                            logging.info ("You are trying to move to the same or a subfolder of %s" % box)
                            continue

            
                        # Store destination with message might come in
                        # handy
                        #print "Setting mc.moved to %s" % destination_path
                        mc.moved=destination_path
                        #print "Destination: %s" % destination_path
                        # Fill the destinations dict
                        if destination_path in destinations:
                            destinations[destination_path][1].append(mc.get_uid())
                        else:
                            destinations[destination_path]= [destination_path_elements, [(mc.get_uid())]]
                            break # Se are done with parsing rules for this message
                # All rules are parsed.a

            if not mc.moved:
                if mc.get("List-Id"):
                    # These generic all.ietf.org  and attendees.ietf.org lists all go to all.ietf.org or attendees.ietf.org
                    m = re.search('<?.*((all|attendees|newcomers|reg)\.(mail\.)?ietf\.org)>?\s*$', mc.get("List-Id"))
                    if m and not destination_path_elements:
                        logging.debug("1 Matched *(all|attendees|newcommers).ietf.org with %s" % m.group(1))
                        destination_path_elements= [
                            configuration_data['List-Id-Destination'],
                            m.group(1)
                            ]
                    
                if mc.get("List-Id"):
                    # Typical mailchimp
                    # List-ID: 10b02e112ca0db3806c3cdfd4mc list <10b02e112ca0db3806c3cdfd4.16513.list-id.mcsv.net>
                    m = re.search('(.*) list <?((\w|-)*(\.(\w|-)*)*)>?\s*$', mc.get("List-Id"))
                    if m and not destination_path_elements and mc.get("Reply-To"):
                        p = re.search('<?.*@((\w|-)*(\.(\w|-)*)*)>?\s*$', mc.get("Reply-To"))
                        logging.debug("1 Matched Mailchimp with %s" % p.group(1))
                        destination_path_elements= [
                            configuration_data['List-Id-Destination'],
                            p.group(1)
                            ]
                    



                if mc.get("List-Id"):
                    # Typical other type of list
                    # List-ID: <7296028.xt.local> get the domain part from the FROM address.
                    m = re.search('<.*\.xt\.local>\s*$', mc.get("List-Id"))
                    if m and not destination_path_elements and mc.get("Reply-To"):
                        p = re.search('<?.*@((\w|-)*(\.(\w|-)*)*)>?\s*$', mc.get("Reply-To"))
                        logging.debug("1 Matched Mailchimp with %s" % p.group(1))
                        destination_path_elements= [
                            configuration_data['List-Id-Destination'],
                            p.group(1)
                            ]
                    

                            
                    # Match anything that vaguely looks like a domain name in <> brackets
                    m = re.search('<?((\w|-)*(\.(\w|-)*)*)>?\s*$', mc.get("List-Id"))
                    if m and not destination_path_elements:
                        logging.debug("2 Matched List-ID with %s" % m.group(1))
                        destination_path_elements= [
                            configuration_data['List-Id-Destination'],
                            m.group(1)
                            ]
              
                        
                        

                if not destination_path_elements:   

                    # The message was not matched Fill a datastructure
                    # for hints about Headers that are Unique
                    # After that Date based archive
                    for header in ["List-Id",
                                   "Reply-To",
                                   "List-Unsubscribe",
                                   "Return-Path",
                                   "Delivered-To",
                                   "X-Env-Sender",
                                   "Delivered-To",
                                   "Envelope-To",
                                   ]:
                        if mc.get(header):
                            key='%s -- %s'%(header,mc.get(header))
                            if key  in hints:
                                if not (hints[key][2][-1]==mc):
                                    hints[key][2].append(mc)
                                    break
                            else:
                                hints[key] = [header,mc.get(header),[mc] ]
                                logging.debug("Keep UID %s"%mc.get_uid())
                    

                    dest_year=mc.get_datetime().year
                    # dest_month=mc.get_datetime().month
                    # if 1 <= dest_month <=3 :
                    #    dest_quarter="Q1"
                    # if 4 <= dest_month <=6 :
                    #    dest_quarter="Q2"
                    # if 7 <= dest_month <=9 :
                    #    dest_quarter="Q3"
                    # if 10 <= dest_month <=12 :
                    #    dest_quarter="Q4"
                
                    destination_path_elements= [
                        configuration_data['Date-Destination'],
                        str(dest_year)  #,dest_quarter
                        ]
                
                if destination_path_elements: # no rulse matched. Just don't archive
                    destination_path= node.delimiter.join(destination_path_elements)
                else:
                    continue

                if re.match(r"\s", destination_path):
                    raise Exception(
                        "Better review the destination, it contains a space: %s" %
                        destination_path)

                if re.match("^"+box, destination_path):
                    # print "You are trying to move to the same or a subfolder of %s" % box
                    continue

                # Fill the destinations dict
                if destination_path in destinations:
                    destinations[destination_path][1].append(mc.get_uid())

                else:
                    destinations[destination_path]= [destination_path_elements, [(mc.get_uid())]]

                    #Done with  looking at all  messages and determining  whether they
        #should be moved
        pbar.finish()              

        # All messages have been parsed.  Now move them to their
        # destinations        move
        if destinations and movethem:
            widgets = ['Moving messages: ', Percentage(), ' ',
                       Bar(marker='=',left='[',right=']'),' ',
                       ETA(), ' '] #see docs for other options
            numbertomove=0
            for (key,mv_data_list) in list(destinations.items()):
                numbertomove+=len(mv_data_list[1])
            
            pbar = ProgressBar(maxval=numbertomove,widgets=widgets)
            logging.debug(f"We need to move {numbertomove} messages" )
        
            pbar.start()     
        
            numbermoved=0

            for (key,mv_data_list) in list(destinations.items()):
                # Check existence of directory, create if necessary
                path=node.delimiter.join(mv_data_list[0])
                logging.debug("Calling List with argument: %s" % path )
                typ, response = c.list(path)
                if typ!='OK':
                    raise Exception ("Failed to execute list command to IMAP server %s"%server)
                #print len(response)

                foundpath=0
                for resp in response:
                    if not resp: continue 
                    dummyf, dummydel, potentialpath= parse_list_response(resp.decode('utf-8'))
                    if potentialpath ==  path:
                        foundpath=1
                if not (foundpath):
                    # Create IMAP Folder
                    logging.debug("Creating Folder %s on Imap Server: %s"%(path,server))
                    typ, dat = c.create(path)
                    if typ!='OK':
                        raise Exception ("Failed to create folder %s on  IMAP server %s. IMAP Server returned: %s"%(path,server,response[0]))
                logging.debug(f"list command for {path} returned: {response[0]}")

                # Copy the messages
                # Do this in chuncks of chunk messages so that the msg lists do not become to long for IMAP to handle them
               
                chunk=50
                length=len(mv_data_list[1])
                chunkcount=length//chunk
                cycle=0
                while ( cycle <= chunkcount ):
                    if (cycle == chunkcount):
                        mv_data= (mv_data_list[1])[cycle*chunk:]
                        numbermoved += ( length % chunk )
                    else:
                        mv_data= (mv_data_list[1])[cycle*chunk:(cycle+1)*chunk]                   
                        numbermoved += chunk
                    typ,response =c.uid('copy',','.join(mv_data),path)  #msg set is comma separated UIDs
                    if typ!='OK':
                        raise Exception ("Failed to copy data to %s on  IMAP server %s. IMAP Server returned: %s"%(path,server,response[0]))

                    # Set the delete flag
                    typ, before = c.uid('store',','.join(mv_data), '+FLAGS', r'(\Deleted)')
                    if typ!='OK':
                        raise Exception ("Failed to set DELETE Flag  IMAP server %s. IMAP Server returned: %s"%(server,response[0]))

                                    #expunge
                    typ,response=c.expunge()
                    if typ!='OK':
                        raise Exception ("Failed to set expunge on IMAP server %s (working on %s):%s"%(server,box,response))
                    
                    pbar.update(numbermoved)
                    cycle += 1

                    
            pbar.finish()
            print ("\nDone")
        else:
            # There were no destinations.. i.e. no matches
            print ("\n(Nothing to be) Done")

        print ("Potential Other Lists")

        sorted_hints= sorted(hints, key=lambda i: int(len(hints[i][2])))
    
    
        for i in sorted_hints:
            
            if ((int(len(hints[i][2]))) < 5) :
                continue
            header=hints[i][0]
            content=hints[i][1]
            messagecont=hints[i][2][0]
            typ,response = c.uid('fetch',messagecont.get_uid(),'FAST')
            if response[0]:
                print ("---------------------------------------------")
                print (f"{header}\":\"{content}\"")
                print (f'Similar messages: {len (hints[i][2])}')
                print (f'Subject: {messagecont.get("Subject")}')
                print (f'Date: {messagecont.get("Date")}')
                print (f'To: {messagecont.get("To")}')
                print ("---------------------------------------------\n")
            #print Results
        print (f"Harverst for {box}: ")
        if destinations:
            for (key,mv_data_list) in list(destinations.items()):
                path=node.delimiter.join(mv_data_list[0])
                if not movethem:
                    print("I would have moved", end='')
                else:
                    print ("- Moved", end='')
                print (f" {len(mv_data_list[1])} messages to {path}")
        else:
            print ("No luck")

                
finally:
    try:
        c.close()
    except:
        pass
    c.logout()


    
    
    
    
    

