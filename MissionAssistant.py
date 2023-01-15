#!/user/bin/python

import os
import math
import logging
from os import write
from PIL import Image, ExifTags, UnidentifiedImageError
import xml.etree.ElementTree as ET
from simplekml import Kml, Style, Polygon
import argparse
import sys, getopt
from scipy.spatial import ConvexHull

def get_args():
        parser = argparse.ArgumentParser("MissionAssistant:", description="Mission Assistant: Inspect drone images on site to detect problems. It also generates a KML polygon of site boundary based on images chosen.",
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

class ImageMetadata:
    def __init__(self, imagename):
        self.image_name = imagename
        self.camera_maker = None
        self.camera_model = None
        self.camera_yaw = None
        self.camera_pitch = None
        self.camera_altitude = None
        self.camera_latitude = None
        self.camera_longitude = None

        gps_all = {}
        try:
            pil_img = Image.open(imagename)
            exif = {ExifTags.TAGS[k]: v for k, v in pil_img._getexif().items() if k in ExifTags.TAGS}
            
            self.camera_maker = exif['Make']
            self.camera_model = exif['Model']
            
            for key in exif['GPSInfo'].keys():
                decoded_value = ExifTags.GPSTAGS.get(key)
                gps_all[decoded_value] = exif['GPSInfo'][key]
            
            long_ref = gps_all.get("GPSLongitudeRef")
            longitude = gps_all.get("GPSLongitude")
            lat_ref = gps_all.get("GPSLatitudeRef")
            latitude = gps_all.get("GPSLatitude")
            
            if long_ref == "W":
                self.camera_longitude = long_in_degrees = -abs(ImageMetadata.convert_to_degrees(longitude))
            else:
                self.camera_longitude = ImageMetadata.convert_to_degrees(longitude)
                
            if lat_ref == "S":
                self.camera_latitude = -abs(ImageMetadata.convert_to_degrees(latitude))
            else:
                self.camera_latitude = ImageMetadata.convert_to_degrees(latitude)
                
            self.camera_altitude = float(gps_all.get("GPSAltitude"))
            
        except Exception as Ex:
            print("Exception while reading {} image metadata: {}".format(imagename, Ex))
            raise # I consider this fatal since we did find relevant exif metadata

        try:
            xmp_string = ImageMetadata.get_xmp_as_xml_string(imagename)
            if xmp_string is not None:
                e = ET.ElementTree(ET.fromstring(xmp_string))
                try:
                    for elt in e.iter():
                        if elt.tag == "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description":
                            self.camera_pitch = float(elt.attrib['{http://www.dji.com/drone-dji/1.0/}GimbalPitchDegree'])
                            self.camera_yaw = float(elt.attrib['{http://www.dji.com/drone-dji/1.0/}GimbalYawDegree'])
                except KeyError as Ex:
                    print("KeyError exception {} : {}".format(imagename, Ex))
                    pass # I don't consider this fatal since we did find lat/long
        except Exception as Ex:
            print("Exception while reading {} extended image metadata: {}".format(imagename, Ex))
            pass # I don't consider this fatal since we did find lat/long
               
    @staticmethod
    def get_xmp_as_xml_string(imagename):
        """Return extended metadata of JPG image. E.g. Yaw, Pitch, Roll is available here"""
        with Image.open(imagename) as im:
            for segment,content in im.applist:
                if segment == 'APP1' and b"<x:xmpmeta" in content:
                    start = content.index(b"<x:xmpmeta")
                    end = content.index(b"</x:xmpmeta>") + len(b"</x:xmpmeta>")
                    return content[start:end].decode()
        return None
    
    @staticmethod
    def convert_to_degrees(value):
        """Returns float angle when given a list of [degrees, minutes, seconds]"""
        d0 = value[0]
        m0 = value[1]
        s0 = value[2]  
        return float(d0) + (float(m0)/60.0) + (float(s0)/3600.0)

class InspectImages:
    NADIRLIMIT = -88.0   # If Gimbal Pitch is < NADIRLIMIT then the image is consider Nadir else Oblique
    cardinals = 36       # Map angle to nearest cardinal direction (specify 4, 8, 12, 18, 36)

    def __init__(self, args):
        self._args = args
        self.input_folder = self._args["infolder"]
        self.output_folder = self._args["outfolder"]
        self.info_flag = self._args["info"]
        self.debug_flag = self._args["debug"]
        self.min_altitude = self._args["alt"][0]
        self.max_altitude = self._args["alt"][1]
        self.image_type = self._args["type"] # Image type Nadir (N), Oblique (O), Any (A). Defaults to (A)
        self.display_kml = None # Shows both the images and the boundary
        self.points = [] # # points is a list of (latitude, longitude) tuples

    @staticmethod
    def get_xmp_as_xml_string(imagename):
        """Return extended metadata of JPG image. E.g. Yaw, Pitch, Roll is available here"""
        with Image.open(imagename) as im:
            for segment,content in im.applist:
                if segment == 'APP1' and b"<x:xmpmeta" in content:
                    start = content.index(b"<x:xmpmeta")
                    end = content.index(b"</x:xmpmeta>") + len(b"</x:xmpmeta>")
                    return content[start:end].decode()
        return None
    
    @staticmethod
    def convert_to_degrees(value):
        """Returns float angle when given a list of [degrees, minutes, seconds]"""
        d0 = value[0]
        m0 = value[1]
        s0 = value[2]  
        return float(d0) + (float(m0)/60.0) + (float(s0)/3600.0)

    @staticmethod
    def degrees_to_cardinals(degrees):
        """Returns a cardinal value for an angle [0, 360] => [0, InspectImages.cardinals-1]. Applies correction to angle."""
        correction = 360.0 / (2.0 * InspectImages.cardinals)
        return math.floor((float((degrees + correction + 360) % 360.0)/360.0) * float(InspectImages.cardinals))
    
    def CreateHull(self):
        self.boundary_kml = [] # This is the boundary derived from image lat/long (convex hull)
        
        # points is a list of (latitude, longitude) tuples (i.e., image locations)
        hull = ConvexHull(self.points)

        # create the KML document
        self.boundary_kml = Kml()

        coords = [(self.points[i][0],self.points[i][1]) for i in hull.vertices]
        coords.append(coords[0])

        polygon = Polygon(outerboundaryis=coords)

        #adding polygon to the boundary_kml
        pol = self.boundary_kml.newpolygon(name='Convex Hull', outerboundaryis=coords)
        pol.style.polystyle.color = '00000000' # 00 for transparent and ff for opaque
        pol.style.polystyle.fill = 1
        
        # Now add polygon to the display_kml (this already has image locations)
        pol = self.display_kml.newpolygon(name='Convex Hull', outerboundaryis=coords)
        pol.style.polystyle.color = '00000000' # 00 for transparent and ff for opaque
        pol.style.polystyle.fill = 1
        
    def process(self):
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
        for i in range(InspectImages.cardinals):
            style_dict[i] = Style()
            style_dict[i].iconstyle.icon.href = 'https://earth.google.com/images/kml-icons/track-directional/track-0.png'
            style_dict[i].iconstyle.heading = i * 360.0/float(InspectImages.cardinals)
        
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
            self.display_kml = Kml()
            folder = self.display_kml.newfolder(name='VIMANA')
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
                    imagemetadata = ImageMetadata(imagename)
                    if imagemetadata.camera_pitch is not None:
                        if imagemetadata.camera_pitch < InspectImages.NADIRLIMIT:
                                    is_nadir = True
                    else:
                        pass
                except UnidentifiedImageError:
                    print("Unable to inspect {}".format(imagename))
                    logger.debug("Unable to inspect {}".format(imagename))
                    continue
                except KeyError:
                    print("Unsupported image format {}".format(imagename))
                    logger.debug("Unsupported image format {}".format(imagename))
                    continue   
                except Exception as Ex:
                    print("No idea what happened. Do you have permission? {}".format(Ex))     
                    continue     
        
                if nadir_or_oblique == 'N':
                    if is_nadir == False:
                        continue
                elif nadir_or_oblique == 'O':
                    if is_nadir == True:
                        continue
                
                if not(self.min_altitude < imagemetadata.camera_altitude < self.max_altitude):
                    continue
                    
                self.points.append(tuple([imagemetadata.camera_longitude, imagemetadata.camera_latitude]))
                pnt = folder.newpoint(name="{0}".format(imagemetadata.camera_altitude), coords=[(imagemetadata.camera_longitude, imagemetadata.camera_latitude)])
                if is_nadir == True or imagemetadata.camera_yaw is None: # If no yaw is available, assume Nadir image
                    pnt.style = shared_nadir_style
                else:
                    pnt.style = style_dict[InspectImages.degrees_to_cardinals(imagemetadata.camera_yaw)] # Assign a predefined style
                    # pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
                    # pnt.style.iconstyle.icon.href = 'https://earth.google.com/images/kml-icons/track-directional/track-0.png'
                    # pnt.style.iconstyle.heading = camera_yaw   # The KML becomes humungous when each point has its personal style

        if found_images == False:
            print("Couldn't find anything to process!!")
            sys.exit(0)            
    
def main(args):
    try:
        image_inspector = InspectImages(args)
        image_inspector.process()
        imagelocations = os.path.join(image_inspector.output_folder, "Images.kml")
        image_inspector.display_kml.save(imagelocations)
        
        image_inspector.CreateHull()
        
        imagelocations = os.path.join(image_inspector.output_folder, "Boundary.kml")
        image_inspector.boundary_kml.save(imagelocations)
        
        imagelocations = os.path.join(image_inspector.output_folder, "Images_and_Boundary.kml")
        image_inspector.display_kml.save(imagelocations)
        
        print("KML files created in {}.".format(image_inspector.output_folder))
    except Exception as Ex:
        print("Unable to create KML. Following error occurred: {}".format(Ex))
        exit(1)
    

if __name__ == "__main__":
    args = get_args()
    
    main(args)
    # main(sys.argv[1:])