#!/user/bin/python

import os
import math
import logging
from os import write
from PIL import Image, ExifTags, UnidentifiedImageError
import xml.etree.ElementTree as ET
from simplekml import Kml, Style
import argparse
import sys, getopt

NADIRLIMIT = -88.0   # If Gimbal Pitch is < NADIRLIMIT then the image is consider Nadir else Oblique
min_altitude = 00.0       # I'm only interested in this range of altitudes
max_altitude = 10000.0
cardinals = 36       # Map angle to nearest cardinal direction (specify 4, 8, 12, 18, 36)

def degrees_to_cardinals(degrees, cardinals):
    """Returns a cardinal value for an angle [0, 360] => [0, cardinals-1]. Applies correction to angle."""
    correction = 360.0 / (2.0 * cardinals)
    return math.floor((float((degrees + correction + 360) % 360.0)/360.0) * float(cardinals))

def convert_to_degrees(value):
    """Returns float angle when given a list of [degrees, minutes, seconds]"""
    d0 = value[0]
    m0 = value[1]
    s0 = value[2]  
    return float(d0) + (float(m0)/60.0) + (float(s0)/3600.0)

def get_xmp_as_xml_string(image_path):
    """Return extended metadata of JPG image. E.g. Yaw, Pitch, Roll is available here"""
    with Image.open(image_path) as im:
        for segment,content in im.applist:
            if segment == 'APP1' and b"<x:xmpmeta" in content:
                start = content.index(b"<x:xmpmeta")
                end = content.index(b"</x:xmpmeta>") + len(b"</x:xmpmeta>")
                return content[start:end].decode()
    return None

def get_args():
    parser = argparse.ArgumentParser("MissionAssistant:", description="Mission Assistant: Inspect drone images on site to detect problems",
                                    epilog="Usage Example: MissionAssistant.exe -i -t N -a 1.0 100.0 D:\DCIM E:\OUTPUT")
    parser.add_argument(
        "-t", 
        "--type", 
        choices=['N', 'O', 'A'], 
        default='A', 
        help="Image type Nadir (N), Oblique (O), Any (A). Defaults to (A)")
    parser.add_argument(
        "-a", 
        "--alt", 
        required=True,
        nargs=2, 
        type=float, 
        help="Specify min followed by max altitude. Only images in this range are considered.")
    parser.add_argument(
        "-d", 
        "--debug", 
        action='store_true', 
        help="Debug option. Collects extra information in log file for debugging purposes.")
    parser.add_argument(
        "-i", 
        "--info", 
        action='store_true', 
        help="Inspect option. Writes image information to log file for informational purposes.")
    parser.add_argument(
        "infolder", 
        help="Input folder with JPG images. All subfolders are also searched for JPG files.")
    parser.add_argument(
        "outfolder", 
        nargs='?', 
        help="KML output is written to this folder. If not specified, it is written to input folder.")

    if len(sys.argv)==1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()
    args_dict = vars(args)
    
    return args_dict

class InspectImages:
    def __init__(self, args):
        self._args = args
        self.input_folder = self._args["infolder"]
        self.output_folder = self._args["outfolder"]
        self.info_flag = self._args["info"]
        self.debug_flag = self._args["debug"]
        self.min_altitude = self._args["alt"][0]
        self.max_altitude = self._args["alt"][1]
        self.image_type = self._args["type"]

    def process(self):
        global NADIRLIMIT, min_altitude, max_altitude, cardinals
        kml = None
        camera_yaw = None
        
        input_folder = self.input_folder
        output_folder = self.output_folder

        if output_folder == None:
            output_folder = input_folder
        
        nadir_or_oblique = self.image_type

        if self.max_altitude < self.min_altitude:
            swap = self.min_altitude
            self.min_altitude = self.max_altitude
            self.max_altitude = swap
        
        
        # Dictionary of styles for oblique images - one for each cardinal direction
        style_dict = {}
        for i in range(cardinals):
            style_dict[i] = Style()
            style_dict[i].iconstyle.icon.href = 'https://earth.google.com/images/kml-icons/track-directional/track-0.png'
            style_dict[i].iconstyle.heading = i * 360.0/float(cardinals)
        
        # Style for nadir images
        shared_nadir_style = Style()
        shared_nadir_style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
        shared_nadir_style.labelstyle.color = 'ff0000ff'  # Red
        
        try:
            logfile_path = os.path.join(output_folder, "LOGFILE.txt")
            logging.basicConfig(filename = logfile_path, filemode = 'w')
            
            if self.info_flag == True:   
                logging.getLogger().setLevel(logging.INFO)
            if self.debug_flag == True:
                logging.getLogger().setLevel(logging.DEBUG)
                
            logger = logging.getLogger()
            kml = Kml()
            folder = kml.newfolder(name='VIMANA')
            # sharedstyle.labelstyle.color = "ff0000ff"  # Red
        except Exception as Ex:
            print("No idea what happened. Do you have permission? {}".format(Ex))
            exit(0)
        
        root_folder = input_folder    
        found_images = False
        
        if self.debug_flag == True:
            print("Debug flag : {}, Info flag : {}".format(self.debug_flag, self.info_flag))
            print("Type of images required: {}".format(self.image_type))
            print("Min altitude : {}, Max altitude : {}".format(self.min_altitude, self.max_altitude))
            
        for input_folder, dir_names, filenames in os.walk(root_folder):
            img_contents = [s for s in os.listdir(input_folder) if s.endswith('.JPG') or s.endswith('.jpg')] # Only pick .JPG or .jpg
                
            if img_contents != []:
                found_images = True
                
            for image in img_contents:
                imagename = os.path.join(input_folder, image)
                
                is_nadir = False
                
                try:
                    xmp_string = get_xmp_as_xml_string(imagename)
                    if xmp_string is None:
                        print("Unable to inspect {}".format(imagename))
                        logger.debug("Unable to inspect {}".format(imagename))
                        continue
                except UnidentifiedImageError:
                    print("Unable to inspect {}".format(imagename))
                    logger.debug("Unable to inspect {}".format(imagename))
                    continue
                                
                logger.debug(xmp_string + '\n')   
                    
                e = ET.ElementTree(ET.fromstring(xmp_string))
                for elt in e.iter():
                    if elt.tag == "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description":
                        try:
                            if float(elt.attrib['{http://www.dji.com/drone-dji/1.0/}GimbalPitchDegree']) < NADIRLIMIT:
                                is_nadir = True
                            else:
                                camera_yaw = float(elt.attrib['{http://www.dji.com/drone-dji/1.0/}GimbalYawDegree'])
                        except KeyError:
                            print("Unsupported image format {}".format(imagename))
                            logger.debug("Unsupported image format {}".format(imagename))
                            continue
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
                    
                    for key in exif['GPSInfo'].keys():
                        decoded_value = ExifTags.GPSTAGS.get(key)
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
                        
                    if not(self.min_altitude < altitude < self.max_altitude):
                        continue
                    
                    # Append image details into this string and dump into log file as a single CSV string
                    img_details = imagename + ","
                    
                    if is_nadir == True:               # Write Image name and whether Nadir (N) or Oblique (O)
                        img_details += 'N'
                    else:
                        img_details += 'O'
                    
                    logger.info(img_details + ',' + str(lat_in_degrees) + ',' + str(long_in_degrees) + ',' + str(altitude))
                    
                    logger.debug(str(gps_all) + '\n')
                    logger.debug(xmp_string + '\n')    
                    
                    pnt = folder.newpoint(name="{0}".format(altitude), coords=[(long_in_degrees, lat_in_degrees)])
                    if is_nadir == True:
                        pnt.style = shared_nadir_style
                    else:
                        pnt.style = style_dict[degrees_to_cardinals(camera_yaw, cardinals)] # Assign a predefined style
                        # pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
                        # pnt.style.iconstyle.icon.href = 'https://earth.google.com/images/kml-icons/track-directional/track-0.png'
                        # pnt.style.iconstyle.heading = camera_yaw   # The KML becomes humungous when each point has its personal style
                
                except Exception as e:
                    print(e)
                    print("This image file ({}) has no GPS info ".format(image))
                    pass

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
    
def main(args):
    image_inspector = InspectImages(args)
    image_inspector.process()

if __name__ == "__main__":
    args = get_args()
    
    main(args)
    # main(sys.argv[1:])