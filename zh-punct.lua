-- 把汉语语境中的引号、破折号、省略号包进 <span class="zhp">，用汉字字体排。
-- 俄语内容（.ru 行内元素、lang="ru" 的块）里的这些符号保持原样。

local PUNCT = {
  [0x2014] = true, [0x2018] = true, [0x2019] = true,
  [0x201C] = true, [0x201D] = true, [0x2026] = true,
}

local function zhp(s)
  return pandoc.Span({pandoc.Str(s)}, pandoc.Attr('', {'zhp'}))
end

local function is_ru(el)
  return el.classes:includes('ru') or el.attributes['lang'] == 'ru'
end

-- 第一遍：所有汉语标点一律包起来
local wrap = {
  Quoted = function(el)
    local open, close = '“', '”'
    if el.quotetype == 'SingleQuote' then open, close = '‘', '’' end
    local out = pandoc.List{zhp(open)}
    out:extend(el.content)
    out:insert(zhp(close))
    return out
  end,
  Str = function(el)
    local has = false
    for _, c in utf8.codes(el.text) do if PUNCT[c] then has = true break end end
    if not has then return nil end
    local out, buf, pbuf = pandoc.List{}, {}, {}
    local function flush(t, isp)
      if #t > 0 then
        local s = table.concat(t)
        out:insert(isp and zhp(s) or pandoc.Str(s))
      end
    end
    for _, c in utf8.codes(el.text) do
      local ch = utf8.char(c)
      if PUNCT[c] then flush(buf, false) buf = {} pbuf[#pbuf + 1] = ch
      else flush(pbuf, true) pbuf = {} buf[#buf + 1] = ch end
    end
    flush(buf, false) flush(pbuf, true)
    return out
  end,
}

-- 第二遍：俄语内容里的包装拆掉
local unwrap_inner = {
  Span = function(el)
    if el.classes:includes('zhp') then return el.content end
  end,
}
local unwrap = {
  Span = function(el) if is_ru(el) then return pandoc.walk_inline(el, unwrap_inner) end end,
  Div  = function(el) if is_ru(el) then return pandoc.walk_block(el, unwrap_inner) end end,
}

return {wrap, unwrap}
