bl_info = {
    "name": "Import GPX (.gpx)",
    "author": "Vladimir Elistratov <prokitektura+support@gmail.com>",
    "version": (1, 0, 2),
    "blender": (2, 80, 0),
    "location": "File > Import > GPX (.gpx)",
    "description": "Import a file in the GPX format (.gpx)",
    "warning": "",
    "wiki_url": "https://github.com/vvoovv/blender-gpx/wiki/Documentation",
    "tracker_url": "https://github.com/vvoovv/blender-gpx/issues",
    "support": "COMMUNITY",
    "category": "Import-Export",
}

import os, sys
import bpy, bmesh
# ImportHelper is a helper class, defines filename and invoke() function which calls the file selector
from bpy_extras.io_utils import ImportHelper

import xml.etree.cElementTree as etree


_isBlender280 = bpy.app.version[1] >= 80
_curveBevelObjectName = "gpx_bevel"

_bevelCurves = {
    "line": ( ( (-1., 0., 0.), (1., 0., 0.) ), False ), # False means: the curve isn't closed
    "square": (
        ( (-1., 0., 0.), (1., 0., 0.), (1., 2., 0.), (-1., 2., 0.) ),
        True # True means: the curve is closed
    )
}


class ImportGpx(bpy.types.Operator, ImportHelper):
    """Import a file in the GPX format (.gpx)"""
    bl_idname = "import_scene.gpx"  # important since its how bpy.ops.import_scene.gpx is constructed
    bl_label = "Import GPX"
    bl_options = {"UNDO"}

    # ImportHelper mixin class uses this
    filename_ext = ".gpx"

    filter_glob = bpy.props.StringProperty(
        default="*.gpx",
        options={"HIDDEN"},
    )

    ignoreGeoreferencing = bpy.props.BoolProperty(
        name="Ignore existing georeferencing",
        description="Ignore existing georeferencing and make a new one",
        default=False,
    )
    
    useElevation = bpy.props.BoolProperty(
        name="Use elevation for z-coordinate",
        description="Use elevation from the track for z-coordinate if checked or make the track flat otherwise",
        default=True,
    )
    
    importType = bpy.props.EnumProperty(
        name = "Import as curve or mesh",
        items = (
            ("curve", "curve", "Blender curve"),
            ("mesh", "mesh", "Blender mesh")
        ),
        description = "Import as Blender curve or mesh",
        default = "curve"
    )
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "useElevation")
        layout.prop(self, "ignoreGeoreferencing")
        if self.bpyproj:
            self.bpyproj.draw(context, layout)
    
    def invoke(self, context, event):
        # check if <bpyproj> is activated and is available in sys.modules
        self.bpyproj = "bpyproj" in (context.preferences.addons if _isBlender280 else context.user_preferences.addons) and sys.modules.get("bpyproj")
        return super().invoke(context, event)

    def execute(self, context):
        # setting active object if there is no active object
        if context.mode != "OBJECT":
            # if there is no object in the scene, only "OBJECT" mode is provided
            if _isBlender280:
                if not context.view_layer.objects.active:
                    context.view_layer.objects.active = context.scene.collection.objects[0]
            else:
                if not context.scene.objects.active:
                    context.scene.objects.active = context.scene.objects[0]
            bpy.ops.object.mode_set(mode="OBJECT")
        
        bpy.ops.object.select_all(action="DESELECT")
        
        name = os.path.basename(self.filepath)
        
        if self.importType == "curve":
            obj = self.makeCurve(context, name)
        else:
            obj = self.makeMesh(context, name)
        
        if _isBlender280:
            bpy.context.scene.collection.objects.link(obj)
        else:
            bpy.context.scene.objects.link(obj)
        
        # remove double vertices
        if _isBlender280:
            context.view_layer.objects.active = obj
        else:
            context.scene.objects.active = obj
        
        if _isBlender280:
            obj.select_set(True)
        else:
            obj.select = True
            bpy.context.scene.update()
        
        return {"FINISHED"}

    def read_gpx_file(self, context):
        # a list of track segments (trkseg)
        segments = []

        minLat = 90
        maxLat = -90
        minLon = 180
        maxLon = -180
        
        gpx = etree.parse(self.filepath).getroot()
        
        for e1 in gpx: # e stands for element
            # Each tag may have the form {http://www.topografix.com/GPX/1/1}tag
            # That's whay we skip curly brackets
            if e1.tag[e1.tag.find("}")+1:] == "trk":
                for e2 in e1:
                    if e2.tag[e2.tag.find("}")+1:] == "trkseg":
                        segment = []
                        for e3 in e2:
                            if e3.tag[e3.tag.find("}")+1:] == "trkpt":
                                lat = float(e3.attrib["lat"])
                                lon = float(e3.attrib["lon"])
                                # calculate track extent
                                if lat<minLat: minLat = lat
                                elif lat>maxLat: maxLat = lat
                                if lon<minLon: minLon = lon
                                elif lon>maxLon: maxLon = lon
                                # check if <trkpt> has <ele>
                                ele = None
                                for e4 in e3:
                                    if e4.tag[e4.tag.find("}")+1:] == "ele":
                                        ele = e4
                                        break
                                point = (lat, lon, float(ele.text)) if self.useElevation and ele is not None else (lat, lon)
                                segment.append(point)
                        segments.append(segment)
        
        projection = self.getProjection(context, lat = (minLat + maxLat)/2, lon = (minLon + maxLon)/2)
        
        return segments, projection
    
    def makeMesh(self, context, name):
        self.bm = bmesh.new()
        
        segments, projection = self.read_gpx_file(context)
        
        # create vertices and edges for the track segments
        for segment in segments:
            prevVertex = None
            for point in segment:
                v = projection.fromGeographic(point[0], point[1])
                v = self.bm.verts.new((v[0], v[1], point[2] if self.useElevation and len(point)==3 else 0))
                if prevVertex:
                    self.bm.edges.new([prevVertex, v])
                prevVertex = v
        
        # finalize
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        # cleanup
        self.bm.free()
        self.bm = None
        
        return bpy.data.objects.new(name, mesh)
    
    def makeCurve(self, context, name):
        curve = bpy.data.curves.new(name, 'CURVE')
        curve.dimensions = '3D'
        curve.twist_mode = 'Z_UP'
        self.curve = curve
        
        segments, projection = self.read_gpx_file(context)
        
        for segment in segments:
            self.createSpline()
            for i, point in enumerate(segment):
                if i:
                    self.spline.points.add(1)
                v = projection.fromGeographic(point[0], point[1])
                self.setSplinePoint((v[0], v[1], point[2] if self.useElevation and len(point)==3 else 0))
        
        # set bevel object
        self.setCurveBevelObject("square")
        
        # cleanup
        self.curve = None
        self.spline = None
        
        return bpy.data.objects.new(name, curve)
    
    def getProjection(self, context, lat, lon):
        # get the coordinates of the center of the Blender system of reference
        scene = context.scene
        if "lat" in scene and "lon" in scene and not self.ignoreGeoreferencing:
            lat = scene["lat"]
            lon = scene["lon"]
        else:
            scene["lat"] = lat
            scene["lon"] = lon
        
        projection = None
        if self.bpyproj:
            projection = self.bpyproj.getProjection(lat, lon)
        if not projection:
            from .transverse_mercator import TransverseMercator
            # fall back to the Transverse Mercator
            projection = TransverseMercator(lat=lat, lon=lon)
        return projection
    
    def createSpline(self, curve=None):
        if not curve:
            curve = self.curve
        self.spline = curve.splines.new('POLY')
        self.pointIndex = 0

    def setSplinePoint(self, point):
        self.spline.points[self.pointIndex].co = (point[0], point[1], point[2], 1.)
        self.pointIndex += 1
    
    def setCurveBevelObject(self, bevelCurveId):
        bevelObj = bpy.data.objects.get(_curveBevelObjectName)
        if not (bevelObj and bevelObj.type == 'CURVE'):
            # create a Blender object of the type 'CURVE' to surve as a bevel object
            bevelCurve = bpy.data.curves.new(_curveBevelObjectName, 'CURVE')
            bevelCurveData, isBevelCurveClosed = _bevelCurves[bevelCurveId]
            
            self.createSpline(bevelCurve)
            self.spline.points.add( len(bevelCurveData)-1 )
            
            for point in bevelCurveData:
                self.setSplinePoint(point)
            
            if isBevelCurveClosed:
                self.spline.use_cyclic_u = True
            
            bevelObj = bpy.data.objects.new(_curveBevelObjectName, bevelCurve)
            
            if _isBlender280:
                bevelObj.hide_viewport = True
                bevelObj.hide_select = True
                bevelObj.hide_render = True
                bpy.context.scene.collection.objects.link(bevelObj)
            else:
                bevelObj.hide = True
                bevelObj.hide_select = True
                bevelObj.hide_render = True
                bpy.context.scene.objects.link(bevelObj)
        
        self.curve.bevel_object = bevelObj


# Only needed if you want to add into a dynamic menu
def menu_func_import(self, context):
    self.layout.operator(ImportGpx.bl_idname, text="GPX (.gpx)")

def register():
    bpy.utils.register_class(ImportGpx)
    if _isBlender280:
        bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    else:
        bpy.types.INFO_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(ImportGpx)
    if _isBlender280:
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    else:
        bpy.types.INFO_MT_file_import.remove(menu_func_import)
