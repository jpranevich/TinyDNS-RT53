#!/usr/bin/python

import getopt, sys, re, route53

from collections import defaultdict

def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "h:z",
                   ["help", "zone="])
    except getopt.GetoptError:
        usage()
    
    # Default:
    zone = "lycos.com."
    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
        if o in ("-z", "--zone"):
            zone = str(a)
    
        # Add a trailing dot, if we don't have one
    if not zone[len(zone) - 1] == '.':
        zone += '.'
        
    conn = route53.connect(aws_access_key_id='xxx', aws_secret_access_key='yyy',)
        
    print "Determined domain name: " + zone
    
    allZones = conn.list_hosted_zones(2000)
    for thisZone in allZones:
        if thisZone.name == zone:
           thisZone.delete(True)
           print "Deleted zone: ", zone
    
def usage():
    print "Not yet!"
    
if __name__ == "__main__":
    main()
