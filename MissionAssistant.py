#!/user/bin/python

import os
from os import write
from PIL import Image, ExifTags
import xml.etree.ElementTree as ET
import simplekml
import argparse
import sys, getopt


def convert_to_degrees(value):
    d0 = value[0]
    m0 = value[1]
    s0 = value[2]
    
    return float(d0) + (float(m0)/60.0) + (float(s0)/3600.0)

def get_xmp_as_xml_string(image_path):
    with Image.open(image_path) as im:
        for segment,content in im.applist:
            if segment == 'APP1' and b"<x:xmpmeta" in content:
                start = content.index(b"<x:xmpmeta")
                end = content.index(b"</x:xmpmeta>") + len(b"</x:xmpmeta>")
                return content[start:end].decode()
    return None    

def main(argv):

    NADIRLIMIT = -88.0   # If Gimbal Pitch is < NADIRLIMIT then the image is consider Nadir else Oblique
    nadir_or_oblique = 'A' # N - Nadir only, O - Oblique only, A - Any

    min_altitude = 00.0       # I'm only interested in this range of altitudes
    max_altitude = 10000.0

    # inputfolder = r"Z:\Temp\Image Processing\NY Trolley\Panorama"
    # inputfolder = (input("Enter folder name: "))
    
    parser = argparse.ArgumentParser("MissionAssistant:", description="Mission Assistant: Inspect drone images on site to detect problems",
                                    epilog="Usage Example: MissionAssistant.exe -i -t N -a 1.0 100.0 D:\DCIM E:\OUTPUT")
    parser.add_argument("-t", "--type", choices=['N', 'O', 'A'], default='A', help="Image type Nadir (N), Oblique (O), Any (A). Defaults to (A)")
    parser.add_argument("-a", "--alt", nargs=2, type=float, help="Specify min followed by max altitude. Only images in this range are considered.")
    parser.add_argument("-d", "--debug", action='store_true', help="Debug option. Collects extra information in log file for debugging purposes.")
    parser.add_argument("-i", "--info", action='store_true', help="Inspect option. Writes image information to log file for informational purposes.")
    parser.add_argument("infolder", help="Input folder with JPG images. Even subfolders are searched for JPG files.")
    parser.add_argument("outfolder", nargs='?', help="KML output is written to this folder. If not specified, it is written to input folder.")

    if len(sys.argv)==1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()

    # print("Input Folder: {}, Output Folder: {}".format(args.infolder, args.outfolder))
    input_folder = args.infolder
    output_folder = args.outfolder

    # print('Input folder is : ', inputfolder)
    if output_folder == None:
        # print("Null outputfolder")
        output_folder = input_folder
    # print('Output folder is : {}'.format(outputfolder))

    nadir_or_oblique = args.type

    # print("Altitude: ", args.alt)

    if args.alt != None:
        min_altitude = args.alt[0]
        max_altitude = args.alt[1]
        if max_altitude < min_altitude:
            swap = min_altitude
            min_altitude = max_altitude
            max_altitude = swap
        
    try:
        logfile_path = os.path.join(output_folder, "LOGFILE.txt")
        logfile = open(logfile_path, 'w')
        # logfile.write("HELLO " + logfile + '\n')
        kml = simplekml.Kml()
    except:
        print("No idea what happened. Do you have permission?")
        exit(0)
    
    root_folder = input_folder    
    found_images = False
    
    if args.debug == True:
        print("Debug flag : {}, Info flag : {}".format(args.debug, args.info))
        print("Type of images required: {}".format(args.type))
        print("Min altitude : {}, Max altitude : {}".format(min_altitude, max_altitude))
        
    for input_folder, dir_names, filenames in os.walk(root_folder):
        img_contents = [s for s in os.listdir(input_folder) if s.endswith('.JPG') or s.endswith('.jpg')] # Only pick .JPG or .jpg
               
        if img_contents != []:
            found_images = True
            
        # print(img_contents)

        for image in img_contents:

            imagename = os.path.join(input_folder, image)
            # print(full_path)
            
            is_nadir = False
            
            #======================
            xmp_string = get_xmp_as_xml_string(imagename)
            
            if args.debug == True:
                logfile.write(xmp_string + '\n')    
                
            # exiftree = ET.fromstring(xmp_string)
            
            e = ET.ElementTree(ET.fromstring(xmp_string))
            for elt in e.iter():
                if elt.tag == "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description":
                    if float(elt.attrib['{http://www.dji.com/drone-dji/1.0/}GimbalPitchDegree']) < NADIRLIMIT:
                        # print("Nadir Image Found")
                        is_nadir = True
                    # else:
                        # print("Not Nadir Image")
            #========================
    
                
            if nadir_or_oblique == 'N':
                if is_nadir == False:
                    continue
            elif nadir_or_oblique == 'O':
                if is_nadir == True:
                    continue
            
            gps_all = {}
            try:
                pil_img = Image.open(imagename)
                exif = {ExifTags.TAGS[k]: v for k, v in pil_img._getexif().items() if k in ExifTags.TAGS}
                # logfile.write(imagename + '\n')
                # logfile.write(str(exif))
                # quit()
                for key in exif['GPSInfo'].keys():
                # for key in exif.keys():
                    #print("This is the code value {}".format(key))
                    decoded_value = ExifTags.GPSTAGS.get(key)
                    # logfile.write("This is its associated label/name {}".format(decoded_value) + '\n')
                    # logfile.write("name {} : value {} \n".format(str(key), str(decoded_value)))
                    gps_all[decoded_value] = exif['GPSInfo'][key]
                
                    
                long_ref = gps_all.get("GPSLongitudeRef")
                longitude = gps_all.get("GPSLongitude")
                lat_ref = gps_all.get("GPSLatitudeRef")
                latitude = gps_all.get("GPSLatitude")
                altitude = float(gps_all.get("GPSAltitude"))
                
                if long_ref == "W":
                    long_in_degrees = -abs(convert_to_degrees(longitude))
                else:
                    long_in_degrees = convert_to_degrees(longitude)
                    
                
                if lat_ref == "S":
                    lat_in_degrees = -abs(convert_to_degrees(latitude))
                else:
                    lat_in_degrees = convert_to_degrees(latitude)
                    
                if not(min_altitude < altitude < max_altitude):
                    continue
                
                if args.info == True:
                    logfile.write(imagename + ",")
                    if is_nadir == True:               # Write Image name and whether Nadir (N) or Oblique (O)
                        logfile.write('N')
                    else:
                        logfile.write('O')
                    logfile.write(',')
                    
                    logfile.write(str(lat_in_degrees)+',') 
                    logfile.write(str(long_in_degrees)+',')
                    logfile.write(str(altitude)+'\n')
                
                if args.debug == True:
                    logfile.write(str(gps_all) + '\n')
                    logfile.write(xmp_string + '\n')    
                
    
                kml.newpoint(coords=[(long_in_degrees, lat_in_degrees)])
            
            except:
                print("This image file ({}) has no GPS info ".format(image))
                pass

            #for k, v in pil_img._getexif().items():
            #    print("This is the key {}".format(k))
            #    print("This is the value {}".format(v))

    if found_images == False:
        print("Couldn't find anything to process!!")
        sys.exit(0)
        
    try:
        imagelocations = os.path.join(output_folder, "Points.kml")
        kml.save(imagelocations)
        print("KML file ({}) created".format(imagelocations))
    except:
        print("Unable to create KML")
        pass
    

if __name__ == "__main__":
    main(sys.argv[1:])