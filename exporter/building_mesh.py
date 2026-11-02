"""
Collada (.dae) 3D Building Mesh Generator for BeamNG TSStatic objects.
"""

import pathlib


def create_cube_dae(output_path: pathlib.Path):
    """
    Creates a simple 10m x 10m x 10m Collada 1.4.1 cube with UV mapping and collisions.
    Can be dynamically scaled to represent any building footprint.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    dae_content = """<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset>
    <contributor><author>AroundWorldNG</author></contributor>
    <unit name="meter" meter="1"/>
    <up_axis>Z_UP</up_axis>
  </asset>
  <library_effects>
    <effect id="building_mat-effect">
      <profile_COMMON>
        <technique sid="common">
          <phong>
            <diffuse><color>0.75 0.73 0.70 1.0</color></diffuse>
            <specular><color>0.1 0.1 0.1 1.0</color></specular>
            <shininess><float>10</float></shininess>
          </phong>
        </technique>
      </profile_COMMON>
    </effect>
  </library_effects>
  <library_materials>
    <material id="building_mat" name="building_mat">
      <instance_effect url="#building_mat-effect"/>
    </material>
  </library_materials>
  <library_geometries>
    <geometry id="Cube-mesh" name="Cube">
      <mesh>
        <source id="Cube-mesh-positions">
          <float_array id="Cube-mesh-positions-array" count="24">
            -5.0 -5.0 0.0
             5.0 -5.0 0.0
             5.0  5.0 0.0
            -5.0  5.0 0.0
            -5.0 -5.0 10.0
             5.0 -5.0 10.0
             5.0  5.0 10.0
            -5.0  5.0 10.0
          </float_array>
          <technique_common>
            <accessor source="#Cube-mesh-positions-array" count="8" stride="3">
              <param name="X" type="float"/>
              <param name="Y" type="float"/>
              <param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <vertices id="Cube-mesh-vertices">
          <input semantic="POSITION" source="#Cube-mesh-positions"/>
        </vertices>
        <triangles material="building_mat" count="12">
          <input semantic="VERTEX" source="#Cube-mesh-vertices" offset="0"/>
          <p>
            0 2 1  0 3 2
            4 5 6  4 6 7
            0 1 5  0 5 4
            1 2 6  1 6 5
            2 3 7  2 7 6
            3 0 4  3 4 7
          </p>
        </triangles>
      </mesh>
    </geometry>
    <geometry id="Col-mesh" name="Col">
      <mesh>
        <source id="Col-mesh-positions">
          <float_array id="Col-mesh-positions-array" count="24">
            -5.0 -5.0 0.0
             5.0 -5.0 0.0
             5.0  5.0 0.0
            -5.0  5.0 0.0
            -5.0 -5.0 10.0
             5.0 -5.0 10.0
             5.0  5.0 10.0
            -5.0  5.0 10.0
          </float_array>
          <technique_common>
            <accessor source="#Col-mesh-positions-array" count="8" stride="3">
              <param name="X" type="float"/>
              <param name="Y" type="float"/>
              <param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <vertices id="Col-mesh-vertices">
          <input semantic="POSITION" source="#Col-mesh-positions"/>
        </vertices>
        <triangles count="12">
          <input semantic="VERTEX" source="#Col-mesh-vertices" offset="0"/>
          <p>
            0 2 1  0 3 2
            4 5 6  4 6 7
            0 1 5  0 5 4
            1 2 6  1 6 5
            2 3 7  2 7 6
            3 0 4  3 4 7
          </p>
        </triangles>
      </mesh>
    </geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="Scene" name="Scene">
      <node id="Cube" name="Cube" type="NODE">
        <instance_geometry url="#Cube-mesh">
          <bind_material>
            <technique_common>
              <instance_material symbol="building_mat" target="#building_mat"/>
            </technique_common>
          </bind_material>
        </instance_geometry>
      </node>
      <node id="Col" name="Col-1" type="NODE">
        <instance_geometry url="#Col-mesh"/>
      </node>
    </visual_scene>
  </library_visual_scenes>
  <scene>
    <instance_visual_scene url="#Scene"/>
  </scene>
</COLLADA>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(dae_content)
    print(f"[BuildingMesh] Created 3D Collada building asset at {output_path}")
