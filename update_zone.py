#!/usr/bin/python

# TODO:
# This script supports TinyDNS (+) and (=)-style A records and CNAMES
# It is built to support additional record types, however they have not yet been added
# It removes all records with split-horizon data as a security precaution, only
# default location records are imported.
# It does not properly notice when a record is removed from a zone, but it can later.
# It does not handle zones files that include multiple zones in one file
# It requires a Z record in each file (and does not support the alternate (.) 
# SOA record format yet.

import getopt, sys, re, route53

from collections import defaultdict

wanted = {}

def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "h:f",
                   ["help", "file="])
    except getopt.GetoptError:
        usage()
    
    # Default:
    filename = "/Users/jpranevich/lycos-dns/mockup.zone"
    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
        if o in ("-f", "--file"):
            filename = str(a)
    
    conn = route53.connect(aws_access_key_id='xxx', aws_secret_access_key='yyy',)
    
    zone = loadFile(filename)
    for key in zone.keys():
        for key2 in zone[key].keys():
            print key, key2, zone[key][key2]
    
    # Now, we have the data, we need to determine what domain name this is for
    # We can get that from the SOA record (Z), first field
    fqdn = zone['Z'].keys()[0]
        
    # Add a trailing dot, if we don't have one
    if not fqdn[len(fqdn) - 1] == '.':
        fqdn += '.'
        
    print "Determined domain name: " + fqdn
    
    found = False
    hostedZone = ''
    allZones = conn.list_hosted_zones(2000)
    for thisZone in allZones:
        if thisZone.name == fqdn:
            found = True
            hostedZone = thisZone
            print "Found it! ", fqdn, thisZone
            break;
      
    if not found:
        hostedZone, changeInfo = conn.create_hosted_zone(fqdn)
    
    # Handle the 'A' records
    doARecords(hostedZone, zone['+'])
        
    # Handle the 'CNAME' records
    doCNAMERecords(hostedZone, zone['C'])
    
def loadFile(filename):
    print "Doing file: " + filename
    
    f = open(filename, 'r');
    lines = f.readlines();
    
    # Pre-processing: remove blanks and comments
    lines = remove_comments(lines)
    
    # Pre-processing: tinyDNS supports many record types that are combinations
    # or real DNS records. Expand them to only have "real" lines in the data file
    lines = expand_special_records(lines)
    
    zone = defaultdict(dict)
    
    # Lines in TinyDNS data files are configured as a record-identifying character, 
    # followed by colon-separated fields which will differ by record type.
    # We want to load all of the records into memory based on type
    for line in lines:
        
        recordType = line[0]
        recordData = re.split(':', line[1:])
        fqdn = recordData[0]
        recordData = recordData[1:]
        
        # The data structure will be a dict-dict-list:
        # A dict of record types containing a dict of hostnames,
        # containtaining matching records for that hostname
        # A single record type/name combination can have multiple
        # lines in a TinyDNS file
            
        if zone.get(recordType) != None:
            if zone[recordType].get(fqdn) != None:
                zone[recordType][fqdn].append(recordData)
            else:
                zone[recordType][fqdn] = list()
                zone[recordType][fqdn].append(recordData)
        else:
            zone[recordType] = dict()
            zone[recordType][fqdn] = list()
            zone[recordType][fqdn].append(recordData)
        
    return zone

def doARecords(hostedZone, a_records):
    
    # TinyDNS A Record Format:
    #      +fqdn:ip:ttl:timestamp:lo
    
    existingARecords = {}
    for existing in hostedZone.record_sets:
        print "Existing: ", existing.name, existing
        existingARecords[existing.name] = existing
        
    # location field in a record is 5    
    a_records = remove_split_horizion(a_records, 5)  
            
    # Now, what we have left is only records that we care about!   
    for fqdn in a_records.keys():
         
        # We take the ttl and timestamp from the first record in the set
        ttl = carefulGet(a_records[fqdn][0], 1)
        timestamp = carefulGet(a_records[fqdn][0], 2)
        
        ipList = list()
        for thisDataLine in a_records[fqdn]:
            ipList.append(thisDataLine[0])

        if not fqdn[len(fqdn) - 1] == '.':
            fqdn += '.'
        
        # wildcard dns is handled with \052 in AWS
        fqdn = fqdn.replace("*", "\\052")
            
        print "Adding or Updating (A): ", fqdn, ipList, ttl
        if existingARecords.has_key(fqdn):
            matchingRecord = existingARecords[fqdn]
            
            # Update the TTL if we need to
            if not str(matchingRecord.ttl) == str(ttl):
                matchingRecord.ttl = ttl
                
            # Always update the IPs; it doesn't hurt
            matchingRecord.records = ipList
            
        else:
            hostedZone.create_a_record(fqdn, ipList, ttl)

def remove_comments(lines):
    
    out = list()
    
    for line in lines:
        # Remove comments and empty lines
        line = re.sub("\s*#.*$", '', line)
        line = re.sub('^\s+', '', line)
        line = re.sub('\s+$', '', line)
            
        if len(line) == 0:
            continue
        else:
            out.append(line)
    
    return out
        
def expand_special_records(records):
    # This function takes the '=' records (A+PTR) in the zone
    # and re-adds them back to hostedZone as '+' and '^' in the
    # correct format. This allows them to be captured in a subsequent
    # step.
    
    #     ^fqdn:p:ttl:timestamp:lo
    #     =fqdn:ip:ttl:timestamp:lo
    #     +fqdn:ip:ttl:timestamp:lo
    
    out = list()
    for record in records:
        
        recordType, fqdn, data = parse_tinydns(record)
        if (recordType == '='):
            # '=' is a A (+) & PTR (^) record
            a_record = '+' + fqdn + ":" + ":".join(data)
            #TODO: Add PTR record. We don't support it yet because
            # it requires files with multiple zones
            out.append(a_record)
        else:
            out.append(record)
        
    return out
             
def parse_tinydns(line):
    recordType = line[0]
    recordData = re.split(':', line[1:])
    fqdn = recordData[0]
    recordData = recordData[1:]
        
    return recordType, fqdn, recordData     
    
def doCNAMERecords(hostedZone, cname_records):
    
    # TinyDNS CNAME Record Format:
    #     Cfqdn:p:ttl:timestamp:lo
    
    existingRecords = {}
    for existing in hostedZone.record_sets:
        print "Existing: ", existing.name, existing
        existingRecords[existing.name] = existing
        
    # location field in cname record is 5    
    cname_records = remove_split_horizion(cname_records, 5)  
            
    # Now, what we have left is only records that we care about!   
    for fqdn in cname_records.keys():
         
        # We take the ttl and timestamp from the first record in the set
        ttl = carefulGet(cname_records[fqdn][0], 1)
        timestamp = carefulGet(cname_records[fqdn][0], 2)
        
        pointerList = list()
        for thisDataLine in cname_records[fqdn]:
            pointerList.append(thisDataLine[0])

        if not fqdn[len(fqdn) - 1] == '.':
            fqdn += '.'
        
        # wildcard dns is handled with \052 in AWS
        fqdn = fqdn.replace("*", "\\052")
            
        print "Adding or Updating (CNAME): ", fqdn, pointerList, ttl
        if existingRecords.has_key(fqdn):
            matchingRecord = existingRecords[fqdn]
            
            # Update the TTL if we need to
            if not str(matchingRecord.ttl) == str(ttl):
                matchingRecord.ttl = ttl
                
            # Always update the IPs; it doesn't hurt
            matchingRecord.records = pointerList
            
        else:
            hostedZone.create_cname_record(fqdn, pointerList, ttl)
            
def remove_split_horizion(records, whichField):
    
    # First, we need to eliminate any records with split horizon enabled. We
    # Can't handle them in AWS and so we are publishing only the all-horizon
    # records.
        
    for fqdn in records.keys():
      
        # This code removes lines with split horizon from the data structure
        thisNameList = records[fqdn]
        newNameList = list()
        for record in thisNameList:
            if carefulGet(record, whichField - 2) == '':
                newNameList.append(record)
            else:
                print "We have a line with split horizon"
                print fqdn, record
        records[fqdn] = newNameList    
         
    for fqdn in records.keys():
        # Second pass to remove names that were ONLY split hozizion since they
        # no longer have any records we care about
        if len(records[fqdn]) == 0:
            print "Removing all records for", fqdn
            del records[fqdn]
            
    return records
                        
def carefulGet(list, index):
    if len(list) >= index + 1:
        return list[index]
    else:
        return ''
    
def delete_zone(conn, fqdn):
    allZones = conn.list_hosted_zones(2000)
    for thisZone in allZones:
        if thisZone.name == fqdn:
           thisZone.delete(True)
           print "Deleted zone: ", fqdn
           
def delete_records_in_zone(hostedZone, fqdn):
    recordSets = hostedZone.record_sets
    for record in recordSets:
        record.delete()
    
def usage():
    print "Not yet!"
    
if __name__ == "__main__":
    main()
