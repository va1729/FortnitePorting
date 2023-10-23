import bpy
import os
import json
import re
from enum import Enum
from math import radians
from mathutils import Matrix, Vector, Euler, Quaternion
from . import ue_format as ueformat

class MeshType(Enum):
	UEFORMAT = 0
	ACTORX = 1

class HatType(Enum):
	HeadReplacement = 0
	Cap = 1
	Mask = 2
	Helmet = 3
	Hat = 4

def hash_code(num):
	return hex(abs(num))[2:]

def get_armature_mesh(obj):
	if obj.type == 'ARMATURE':
		return obj.children[0]

	if obj.type == 'MESH':
		return obj

def append_data():
	addon_dir = os.path.dirname(os.path.splitext(__file__)[0])
	with bpy.data.libraries.load(os.path.join(addon_dir, "fortnite_porting_data.blend")) as (data_from, data_to):
		for node_group in data_from.node_groups:
			if not bpy.data.node_groups.get(node_group):
				data_to.node_groups.append(node_group)

		'''for obj in data_from.objects:
			if not bpy.data.objects.get(obj):
				data_to.objects.append(obj)

		for mat in data_from.materials:
			if not bpy.data.materials.get(mat):
				data_to.materials.append(mat)'''

def create_collection(name):
	if name in bpy.context.view_layer.layer_collection.children:
		bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children.get(name)
		return
	bpy.ops.object.select_all(action='DESELECT')
	
	new_collection = bpy.data.collections.new(name)
	bpy.context.scene.collection.children.link(new_collection)
	bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children.get(new_collection.name)

def constraint_object(child: bpy.types.Object, parent: bpy.types.Object, bone: str, rot=[0, radians(90), 0]):
	constraint = child.constraints.new('CHILD_OF')
	constraint.target = parent
	constraint.subtarget = bone
	child.rotation_mode = 'XYZ'
	child.rotation_euler = rot
	constraint.inverse_matrix = Matrix()

def first(target, expr, default=None):
	if not target:
		return None
	filtered = filter(expr, target)

	return next(filtered, default)

def where(target, expr):
	if not target:
		return None
	filtered = filter(expr, target)

	return list(filtered)

def any(target, expr):
	if not target:
		return None

	filtered = list(filter(expr, target))
	return len(filtered) > 0

def merge_skeletons(parts):
	bpy.ops.object.select_all(action='DESELECT')

	merge_parts = []
	constraint_parts = []

	for part in parts:
		if (meta := part.get("Meta")) and meta.get("AttachToSocket") and meta.get("Socket") not in ["Face", None]:
			constraint_parts.append(part)
		else:
			merge_parts.append(part)

	# merge skeletons
	for part in merge_parts:
		data = part.get("Data")
		mesh_type = data.get("Type")
		skeleton = part.get("Skeleton")

		if mesh_type == "Body":
			bpy.context.view_layer.objects.active = skeleton

		skeleton.select_set(True)

	bpy.ops.object.join()
	master_skeleton = bpy.context.active_object
	bpy.ops.object.select_all(action='DESELECT')

	# merge meshes
	for part in merge_parts:
		data = part.get("Data")
		mesh_type = data.get("Type")
		mesh = part.get("Mesh")

		if mesh_type == "Body":
			bpy.context.view_layer.objects.active = mesh

		mesh.select_set(True)

	bpy.ops.object.join()
	bpy.ops.object.select_all(action='DESELECT')

	# rebuild master bone tree
	bone_tree = {}
	for bone in master_skeleton.data.bones:
		try:
			bone_reg = re.sub(".\d\d\d", "", bone.name)
			parent_reg = re.sub(".\d\d\d", "", bone.parent.name)
			bone_tree[bone_reg] = parent_reg
		except AttributeError:
			pass

	bpy.context.view_layer.objects.active = master_skeleton
	bpy.ops.object.mode_set(mode='EDIT')
	bpy.ops.armature.select_all(action='DESELECT')
	bpy.ops.object.select_pattern(pattern="*.[0-9][0-9][0-9]")
	bpy.ops.armature.delete()

	skeleton_bones = master_skeleton.data.edit_bones

	for bone, parent in bone_tree.items():
		if target_bone := skeleton_bones.get(bone):
			target_bone.parent = skeleton_bones.get(parent)

	bpy.ops.object.mode_set(mode='OBJECT')

	# constraint meshes
	for part in constraint_parts:
		skeleton = part.get("Skeleton")
		meta = part.get("Meta")
		socket = meta.get("Socket")
		if socket is None:
			return

		if socket.casefold() == "hat":
			socket = "head"

		constraint_object(skeleton, master_skeleton, socket)


location_mappings = {
	"Diffuse": (-300, -75),
	"M": (-300, -120),
	"SpecularMasks": (-300, -275),
	"Normals": (-300, -315)
}

texture_mappings = {
	"Diffuse": "Diffuse",
	"M": "M",
	"Mask": "M",
	"SpecularMasks": "SpecularMasks",
	"SRM": "SpecularMasks",
	"Normals": "Normals"
}

scalar_mappings = {
	"RoughnessMin": "Roughness Min",
	"RawRoughnessMin": "Roughness Min",
	"RoughnessMax": "Roughness Max",
	"RawRoughnessMax": "Roughness Max",
}

vector_mappings = {
	"Skin Boost Color And Exponent": ("Skin Color", "Skin Boost")
}

switch_mappings = {
	"SwizzleRoughnessToGreen": "SwizzleRoughnessToGreen",
}

class ImportTask:
	def run(self, response):
		print(json.dumps(response))

		self.imported_materials = {}
		self.assets_folder = response.get("AssetsFolder")
		self.options = response.get("Options")

		append_data()
		datas = response.get("Data")
		for index, data in enumerate(datas):
			self.import_data(data, index)

	def import_data(self, data, import_index):
		if self.options.get("ImportCollection"):
			create_collection(data.get("Name"))

		export_type = data.get("Type")

		meshes_to_import = data.get("OverrideMeshes")
		for mesh in data.get("Meshes"):
			if not any(meshes_to_import, lambda override_mesh: override_mesh.get("Type") == mesh.get("Type")):
				meshes_to_import.append(mesh)

		def get_meta(search_props):
			out_props = {}
			for mesh in meshes_to_import:
				meta = mesh.get("Meta")
				if found_key := first(meta.keys(), lambda key: key in search_props):
					out_props[found_key] = meta.get(found_key)
			return out_props

		imported_meshes = []
		def import_mesh(mesh):
			mesh_type = mesh.get("Type")

			imported_object = self.import_model(mesh.get("Path"))
			imported_mesh = get_armature_mesh(imported_object)
			imported_meshes.append({
				"Skeleton": imported_object,
				"Mesh": imported_mesh,
				"Data": mesh,
				"Meta": mesh.get("Meta")
			})

			match mesh_type:
				case "Body":
					meta = get_meta(["SkinColor"])
				case "Head":
					meta = get_meta(["MorphNames", "HatType"])

					shape_keys = imported_mesh.data.shape_keys
					if (morph_name := meta.get("MorphNames").get(meta.get("HatType"))) and shape_keys is not None:
						for key in shape_keys.key_blocks:
							if key.name.casefold() == morph_name.casefold():
								key.value = 1.0
				case _:
					meta = get_meta([])

			for material in mesh.get("Materials"):
				index = material.get("Slot")
				self.import_material(imported_mesh.material_slots[index], material, meta)

			for override_material in mesh.get("OverrideMaterials"):
				index = override_material.get("Slot")
				if index >= len(imported_mesh.material_slots):
					continue

				overridden_material = imported_mesh.material_slots[index].material
				for slot in imported_mesh.material_slots:
					if slot.material.name.casefold() == overridden_material.name.casefold():
						self.import_material(imported_mesh.material_slots[slot.slot_index], override_material, meta)

			for variant_override_material in data.get("OverrideMaterials"):
				slots = where(imported_mesh.material_slots, lambda slot: slot.name.casefold() == variant_override_material.get("MaterialNameToSwap").casefold())
				for slot in slots:
					self.import_material(slot, variant_override_material, meta)


		for mesh in meshes_to_import:
			import_mesh(mesh)

		if export_type == "Outfit" and self.options.get("MergeSkeletons"):
			merge_skeletons(imported_meshes)

	def import_material(self, material_slot, material_data, meta_data):
		material_name = material_data.get("Name")
		material_hash = material_data.get("Hash")

		if existing := self.imported_materials.get(material_hash):
			material_slot.material = existing
			return

		if material_slot.material.name.casefold() != material_name.casefold():
			material_slot.material = bpy.data.materials.new(material_name)

		self.imported_materials[material_hash] = material_slot.material
		material = material_slot.material
		material.use_nodes = True
		nodes = material.node_tree.nodes
		nodes.clear()
		links = material.node_tree.links
		links.clear()

		textures = material_data.get("Textures")
		scalars = material_data.get("Scalars")
		vectors = material_data.get("Vectors")
		switches = material_data.get("Switches")
		component_masks = material_data.get("ComponentMasks")

		output_node = nodes.new(type="ShaderNodeOutputMaterial")
		output_node.location = (200, 0)

		shader_node = nodes.new(type="ShaderNodeGroup")
		shader_node.name = "FP Material"
		shader_node.node_tree = bpy.data.node_groups.get(shader_node.name)
		shader_node.inputs["AO"].default_value = self.options.get("AmbientOcclusion")
		shader_node.inputs["Cavity"].default_value = self.options.get("Cavity")
		shader_node.inputs["Subsurface"].default_value = self.options.get("Subsurface")
		links.new(shader_node.outputs[0], output_node.inputs[0])

		def texture_param(data):
			name = data.get("Name")
			path = data.get("Value")

			if name == "SRM":
				shader_node.inputs["SwizzleRoughnessToGreen"].default_value = 1

			if (slot := texture_mappings.get(name)) is None:
				return

			node = nodes.new(type="ShaderNodeTexImage")
			node.image = self.import_image(path)
			node.image.alpha_mode = 'CHANNEL_PACKED'
			node.image.colorspace_settings.name = "sRGB" if data.get("sRGB") else "Non-Color"
			node.location = location_mappings[slot]
			node.hide = True
			links.new(node.outputs[0], shader_node.inputs[slot])

		def scalar_param(data):
			name = data.get("Name")
			value = data.get("Value")
			if (slot := scalar_mappings.get(name)) is None:
				return

			shader_node.inputs[slot].default_value = value

		def vector_param(data):
			name = data.get("Name")
			value = data.get("Value")
			if (slot_data := vector_mappings.get(name)) is None:
				return

			color_slot, alpha_slot = slot_data

			shader_node.inputs[color_slot].default_value = (value["R"], value["G"], value["B"], 1.0)
			if alpha_slot is not None:
				shader_node.inputs[alpha_slot].default_value = value["A"]

		def switch_param(data):
			name = data.get("Name")
			value = data.get("Value")
			if (slot := switch_mappings.get(name)) is None:
				return

			shader_node.inputs[slot].default_value = 1 if value else 0


		for texture in textures:
			texture_param(texture)

		for scalar in scalars:
			scalar_param(scalar)

		for vector in vectors:
			vector_param(vector)

		for switch in switches:
			switch_param(switch)

		if (skin_color := meta_data.get("SkinColor")) and skin_color["A"] != 0:
			shader_node.inputs["Skin Color"].default_value = (skin_color["R"], skin_color["G"], skin_color["B"], 1.0)
			shader_node.inputs["Skin Boost"].default_value = skin_color["A"]

	def import_image(self, path: str):
		path, name = path.split(".")
		if existing := bpy.data.images.get(name):
			return existing

		path = path[1:] if path.startswith("/") else path
		ext = "png"
		texture_path = os.path.join(self.assets_folder, path + "." + ext)

		if not os.path.exists(texture_path):
			return None

		return bpy.data.images.load(texture_path, check_existing=True)

	def import_model(self, path: str):
		path = path[1:] if path.startswith("/") else path
		mesh_path = os.path.join(self.assets_folder, path.split(".")[0])

		extension = MeshType(self.options.get("MeshExportType"))
		if extension == MeshType.UEFORMAT:
			mesh_path += ".uemodel"
		elif extension == MeshType.ACTORX:
			if os.path.exists(mesh_path + ".psk"):
				mesh_path += ".psk"
			if os.path.exists(mesh_path + ".pskx"):
				mesh_path += ".pskx"

		return ueformat.import_file(mesh_path)