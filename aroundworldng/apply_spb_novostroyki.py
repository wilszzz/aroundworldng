with open(r'c:\me\Antigravity projects\aroundworldng\mod\lua\ge\extensions\e2r\generator.lua', 'r', encoding='utf-8') as f:
    text = f.read()

wallMat_old = """  local panel = region.panel or {'pnl_grey', 'pnl_beige', 'pnl_pink', 'pnl_blue', 'pnl_white'}
  local loggia = {'lgg_cream', 'lgg_grey', 'lgg_pink'}
  local brick = region.brick or {'brk_red', 'brk_white'}
  local plaster = region.plaster or {'pls_yellow', 'pls_cream', 'pls_peach', 'pls_green', 'pls_blue', 'pls_grey'}
  local family
  -- a tower of this century, unless its tags say what it is built of
  if region.new and not material and height >= 26 and h % 4 == 0 then family = region.new
  elseif material == 'brick' then family = brick
  elseif material == 'panel' or material == 'concrete' or material == 'reinforced_concrete' then family = height >= 26 and h % 3 ~= 0 and loggia or panel
  elseif material == 'plaster' or material == 'stucco' then family = plaster
  elseif height < 8 then family = h % 5 < 3 and plaster or brick   -- a house is not a panel block
  elseif look.buildings == 'panel' and not region.byHeight then family = height >= 26 and (h % 3 ~= 0 and loggia or panel) or panel
  elseif look.buildings == 'brick' then family = brick
  elseif look.buildings == 'plaster' then family = plaster
  elseif region.brick and not region.panel then family = h % 5 < 2 and brick or plaster   -- no panel blocks here
  elseif height >= 26 then family = h % 9 < 4 and loggia or panel
  elseif height >= 14 then family = h % 20 < 8 and panel or h % 20 < 15 and brick or plaster
  else family = h % 5 < 3 and plaster or brick end
  return 'wall_' .. family[math.floor(h / 7) % #family + 1]"""

wallMat_new = """  local novostroyki = {
    'pls_d_new', 'pls_d_euro', 'pls_d_euro_warm', 'pls_d_blue', 'pls_d_tile',
    'brk_d_new', 'brk_d_sil', 'brk_d_dark', 'brk_d_red',
    'off_ribbon', 'off_blue', 'pnl_white', 'pnl_beige', 'pls_d_pink'
  }
  local brick = {'brk_d_new', 'brk_d_sil', 'brk_d_dark', 'brk_d_red'}
  local plaster = {'pls_d_new', 'pls_d_euro', 'pls_d_euro_warm', 'pls_d_blue', 'pls_d_tile'}
  local family
  if material == 'brick' then family = brick
  elseif material == 'plaster' or material == 'stucco' then family = plaster
  elseif height >= 14 then family = novostroyki
  elseif height < 8 then family = h % 2 == 0 and plaster or brick
  else family = novostroyki end
  return 'wall_' .. family[h % #family + 1]"""

assert wallMat_old in text, 'wallMat_old not found in text!'
text = text.replace(wallMat_old, wallMat_new)

# Now check blank end wall replacement
end_old = "if length < 16 and (kind:find('wall_pnl_', 1, true) == 1 or kind:find('wall_lgg_', 1, true) == 1 or kind:find('wall_brk_', 1, true) == 1) then wallKind = kind .. '_end' end"
end_new = "if length < 4.2 and (kind:find('wall_pnl_', 1, true) == 1 or kind:find('wall_lgg_', 1, true) == 1 or kind:find('wall_brk_', 1, true) == 1) then wallKind = kind .. '_end' end"

assert end_old in text, 'end_old not found in text!'
text = text.replace(end_old, end_new)

# Also update BLD.spec.postsoviet for full consistency
spec_old = """    panel = 'pnl_grey 3 pnl_beige 3 pnl_pink 2 pnl_blue 2 pnl_white 2 pnl_patch_grey 3 pnl_patch_beige 3 pnl_patch_white 2',
    brick = 'brk_d_sil 4 brk_d_red 3 brk_d_old 2 brk_red 1 brk_white 1',
    plaster = 'pls_d_dash 4 pls_d_stalin 3 pls_d_stalin_red 2 pls_d_aged 2 pls_d_flake 2 pls_yellow 1 pls_cream 1 pls_peach 1 pls_grey 1',
    new = 'pls_d_new 2 brk_d_new 1',"""

spec_new = """    panel = 'pls_d_new 3 pls_d_euro 3 pls_d_blue 2 pls_d_tile 2 brk_d_new 2 pnl_white 2 pnl_beige 1',
    brick = 'brk_d_new 4 brk_d_sil 3 brk_d_dark 2 brk_d_red 2',
    plaster = 'pls_d_new 3 pls_d_euro 3 pls_d_euro_warm 2 pls_d_blue 2 pls_d_tile 2',
    new = 'pls_d_new 3 brk_d_new 3 pls_d_blue 2 off_ribbon 2 off_blue 2',"""

if spec_old in text:
    text = text.replace(spec_old, spec_new)

import lupa
lua = lupa.LuaRuntime()
lua.compile(text)
print('Compilation successful!')

with open(r'c:\me\Antigravity projects\aroundworldng\mod\lua\ge\extensions\e2r\generator.lua', 'w', encoding='utf-8') as f:
    f.write(text)
print('Successfully written updated generator.lua!')
