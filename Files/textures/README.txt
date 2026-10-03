PBR textures for the generator's materials
===========================================

Drop free PBR map sets here, named after the pack they came from:

    T_WoodDark_01_BaseColor.jpg
    T_WoodDark_01_Normal.png
    T_WoodDark_01_Roughness.jpg

Map names: basecolor / normal / roughness / metallic - case does not matter
(BaseColor, _ROUGHNESS, .PNG all fine). Extensions: .png .jpg .jpeg .tga .bmp
.webp.

Which material a set feeds is decided in materials.txt next to this file:

    MI_WoodDark_01 = T_WoodDark_01
    MI_WoodLight_01 = T_WoodLight_001

Left side = material name from the panel, right side = set prefix of the
files. Add a line when you drop a new pack; a material without a line looks
for files named {material}_{map}, so both ways work.

Maps are optional: basecolor alone already works; add the rest as you find
them. Every map present is picked up on the next generation - materials are
created once per .blend, so in an existing scene delete the material (or its
image nodes) and regenerate.

When a map set is found it overrides the flat Base Color / Roughness / Metallic
defaults; missing maps keep the defaults from ensure_material().

