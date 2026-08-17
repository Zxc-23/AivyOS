# HTML to Markdown converter for AivyOS Technical Engineering Document
# Properly handles code blocks, tables, lists, callouts, and special divs

# --- Helper functions (must be defined before use) ---

function Convert-InlineHtml {
    param([string]$text)
    $text = $text -replace '<strong>(.*?)</strong>', '**$1**'
    $text = $text -replace '<em>(.*?)</em>', '*$1*'
    $text = $text -replace '<code>(.*?)</code>', '`$1`'
    $text = $text -replace '<a href="(.*?)".*?>(.*?)</a>', '[$2]($1)'
    $text = $text -replace '<span class="badge[^"]*">(.*?)</span>', '`$1`'
    $text = $text -replace '<span class="accel">\s*(.*?)</span>', ' $1'
    $text = $text -replace '<span[^>]*>(.*?)</span>', '$1'
    $text = $text -replace '<br\s*/?>', "`n"
    $text = $text -replace '<[^>]+>', ''
    $text = $text -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>' -replace '&quot;','"' -replace '&#39;',"'"
    return $text.Trim()
}

function Convert-Table {
    param([string]$tableHtml)
    $result = [System.Collections.ArrayList]::new()
    $headers = @()
    $rows = @()

    $theadMatch = [regex]::Match($tableHtml, '(?s)<thead>(.*?)</thead>')
    if ($theadMatch.Success) {
        $thMatches = [regex]::Matches($theadMatch.Groups[1].Value, '<th>(.*?)</th>')
        foreach ($th in $thMatches) {
            $headers += (Convert-InlineHtml $th.Groups[1].Value)
        }
    }

    $tbodyMatch = [regex]::Match($tableHtml, '(?s)<tbody>(.*?)</tbody>')
    $bodyHtml = if ($tbodyMatch.Success) { $tbodyMatch.Groups[1].Value } else { $tableHtml }
    $trMatches = [regex]::Matches($bodyHtml, '(?s)<tr>(.*?)</tr>')
    foreach ($tr in $trMatches) {
        $tdMatches = [regex]::Matches($tr.Groups[1].Value, '<td>(.*?)</td>')
        $row = @()
        foreach ($td in $tdMatches) {
            $row += (Convert-InlineHtml $td.Groups[1].Value)
        }
        if ($row.Count -gt 0) { $rows += ,@($row) }
    }

    if ($headers.Count -eq 0 -and $rows.Count -eq 0) { return $null }
    if ($headers.Count -eq 0 -and $rows.Count -gt 0) {
        $headers = $rows[0]
        if ($rows.Count -gt 1) { $rows = $rows[1..($rows.Count - 1)] } else { $rows = @() }
    }

    [void]$result.Add("| $($headers -join ' | ') |")
    [void]$result.Add("| $(($headers | ForEach-Object { '---' }) -join ' | ') |")
    foreach ($row in $rows) {
        while ($row.Count -lt $headers.Count) { $row += '' }
        [void]$result.Add("| $($row -join ' | ') |")
    }
    return $result
}

function Convert-MenuTree {
    param([string]$menuHtml)
    $result = [System.Collections.ArrayList]::new()
    # Process line by line, tracking nesting level
    $lines = $menuHtml -split "`n"
    $indent = 0
    foreach ($mline in $lines) {
        $mline = $mline.Trim()
        if ($mline -eq '') { continue }
        if ($mline -match '<div class="root">(.*?)</div>') {
            [void]$result.Add($matches[1])
        } elseif ($mline -match '<div class="sep">(.*?)</div>') {
            [void]$result.Add($matches[1])
        } elseif ($mline -match '<div class="item(?: disabled)?">(.*?)(?:<span class="accel">\s*(.*?)</span>)?</div>') {
            $itemText = $matches[1].Trim()
            $accel = $matches[2]
            $prefix = '  ' * $indent
            if ($accel) {
                [void]$result.Add("${prefix}${itemText} ${accel}")
            } else {
                [void]$result.Add("${prefix}${itemText}")
            }
        } elseif ($mline -match '<div class="sub">') {
            $indent++
        } elseif ($mline -match '</div>') {
            if ($indent -gt 0) { $indent-- }
        }
    }
    return $result
}

function ExtractDivContent {
    param([array]$lines, [int]$startIndex)
    $content = ''
    $depth = 1
    $i = $startIndex + 1
    while ($i -lt $lines.Count -and $depth -gt 0) {
        $cl = $lines[$i].Trim()
        if ($cl -match '<div') { $depth++ }
        if ($cl -match '</div>') { $depth-- }
        if ($depth -gt 0) { $content += $cl + "`n" }
        $i++
    }
    return @{ Content = $content; EndIndex = $i }
}

# --- Main conversion ---

$baseDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$htmlPath = Join-Path $baseDir "AivyOS_Technical_Engineering_Document.html"
$mdPath = Join-Path $baseDir "AivyOS_Technical_Engineering_Document.md"

$html = [System.IO.File]::ReadAllText($htmlPath, [System.Text.Encoding]::UTF8)
$output = [System.Collections.ArrayList]::new()

# Step 1: Extract code blocks and replace with placeholders
$codeBlocks = [System.Collections.ArrayList]::new()
$cbMatches = [regex]::Matches($html, '(?s)<pre><code>(.*?)</code></pre>')
foreach ($m in $cbMatches) {
    $code = $m.Groups[1].Value
    $code = $code -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>' -replace '&quot;','"' -replace '&#39;',"'"
    $code = $code.TrimEnd("`n", "`r")
    [void]$codeBlocks.Add($code)
}
for ($i = $cbMatches.Count - 1; $i -ge 0; $i--) {
    $html = $html.Remove($cbMatches[$i].Index, $cbMatches[$i].Length).Insert($cbMatches[$i].Index, "[[CODEBLOCK_$i]]")
}

# Step 2: Extract TOC
$tocHtml = [regex]::Match($html, '(?s)<aside class="toc">(.*?)</aside>').Groups[1].Value
$tocHeading = [regex]::Match($tocHtml, '<h3>(.*?)</h3>').Groups[1].Value
[void]$output.Add("## $tocHeading")
[void]$output.Add("")
$tocH4Matches = [regex]::Matches($tocHtml, '(?s)<h4>(.*?)</h4>\s*<ul>(.*?)</ul>')
foreach ($h4 in $tocH4Matches) {
    $sectionTitle = $h4.Groups[1].Value
    [void]$output.Add("**$sectionTitle**")
    $links = [regex]::Matches($h4.Groups[2].Value, '<a href="#(.*?)">(.*?)</a>')
    foreach ($link in $links) {
        $anchor = $link.Groups[1].Value
        $text = $link.Groups[2].Value
        [void]$output.Add("- [$text](#$anchor)")
    }
    [void]$output.Add("")
}
[void]$output.Add("---")
[void]$output.Add("")

# Step 3: Extract main content (exclude footer which is handled separately)
$contentMatch = [regex]::Match($html, '(?s)<main class="content">(.*?)<footer>')
if ($contentMatch.Success) {
    $contentHtml = $contentMatch.Groups[1].Value
} else {
    $contentHtml = [regex]::Match($html, '(?s)<main class="content">(.*?)</main>').Groups[1].Value
}

# Step 4: Convert HTML to Markdown line by line
$lines = $contentHtml -split "`n"
$i = 0
while ($i -lt $lines.Count) {
    $line = $lines[$i].TrimStart()

    # Skip empty lines and comments
    if ($line -eq '') { $i++; continue }
    if ($line -match '^<!--') {
        while ($i -lt $lines.Count -and $lines[$i] -notmatch '-->') { $i++ }
        $i++
        continue
    }

    # Cover div
    if ($line -match '<div class="cover">') {
        $extract = ExtractDivContent $lines $i
        $coverHtml = $extract.Content
        $i = $extract.EndIndex
        # Extract h1
        $h1Match = [regex]::Match($coverHtml, '<h1>(.*?)</h1>')
        if ($h1Match.Success) {
            [void]$output.Add("# $($h1Match.Groups[1].Value)")
            [void]$output.Add("")
        }
        # Extract subtitle
        $subMatch = [regex]::Match($coverHtml, 'class="subtitle">(.*?)</div>')
        if ($subMatch.Success) {
            [void]$output.Add("**$($subMatch.Groups[1].Value)**")
            [void]$output.Add("")
        }
        # Extract meta
        $metaItems = [regex]::Matches($coverHtml, 'class="label">(.*?)</span><span class="value">(.*?)</span>')
        if ($metaItems.Count -gt 0) {
            $headers = @()
            $values = @()
            foreach ($item in $metaItems) {
                $headers += $item.Groups[1].Value
                $values += $item.Groups[2].Value
            }
            $headerLine = $headers -join ' | '
            $valueLine = $values -join ' | '
            $sepLine = ($headers | ForEach-Object { '---' }) -join ' | '
            [void]$output.Add("| $headerLine |")
            [void]$output.Add("| $sepLine |")
            [void]$output.Add("| $valueLine |")
            [void]$output.Add("")
        }
        continue
    }

    # Headings
    if ($line -match '<h2[^>]*>(.*?)</h2>') {
        $text = Convert-InlineHtml $matches[1]
        # Preserve h2 anchor ids (e.g. ch1) so the #chN TOC links work in Markdown.
        $anchorMatch = [regex]::Match($line, '<h2[^>]*id="([^"]+)"[^>]*>')
        if ($anchorMatch.Success) {
            [void]$output.Add("<a id=""$($anchorMatch.Groups[1].Value)""></a>")
        }
        [void]$output.Add("## $text")
        [void]$output.Add("")
        $i++
        continue
    }
    if ($line -match '<h3[^>]*>(.*?)</h3>') {
        $text = Convert-InlineHtml $matches[1]
        [void]$output.Add("### $text")
        [void]$output.Add("")
        $i++
        continue
    }
    if ($line -match '<h4[^>]*>(.*?)</h4>') {
        $text = Convert-InlineHtml $matches[1]
        [void]$output.Add("#### $text")
        [void]$output.Add("")
        $i++
        continue
    }

    # Paragraph
    if ($line -match '^<p>(.*?)</p>$') {
        $text = Convert-InlineHtml $matches[1]
        [void]$output.Add($text)
        [void]$output.Add("")
        $i++
        continue
    }

    # Unordered list
    if ($line -match '^<ul>') {
        $listHtml = ''
        while ($i -lt $lines.Count -and $lines[$i].Trim() -ne '</ul>') {
            $listHtml += $lines[$i].Trim()
            $i++
        }
        $i++
        $items = [regex]::Matches($listHtml, '<li>(.*?)</li>')
        foreach ($item in $items) {
            $text = Convert-InlineHtml $item.Groups[1].Value
            [void]$output.Add("- $text")
        }
        [void]$output.Add("")
        continue
    }

    # Ordered list (including step-list)
    if ($line -match '^<ol') {
        $listHtml = ''
        while ($i -lt $lines.Count -and $lines[$i].Trim() -ne '</ol>') {
            $listHtml += $lines[$i].Trim()
            $i++
        }
        $i++
        $items = [regex]::Matches($listHtml, '<li>(.*?)</li>')
        $num = 1
        foreach ($item in $items) {
            $text = Convert-InlineHtml $item.Groups[1].Value
            [void]$output.Add("$num. $text")
            $num++
        }
        [void]$output.Add("")
        continue
    }

    # Callout
    if ($line -match '<div class="callout') {
        $extract = ExtractDivContent $lines $i
        $calloutHtml = $extract.Content.Trim()
        $i = $extract.EndIndex
        $text = Convert-InlineHtml $calloutHtml
        [void]$output.Add("> $text")
        [void]$output.Add("")
        continue
    }

    # Table
    if ($line -match '<div class="table-wrap">') {
        $tableHtml = ''
        while ($i -lt $lines.Count -and $lines[$i].Trim() -ne '</div>') {
            $tableHtml += $lines[$i].Trim()
            $i++
        }
        $i++
        $table = Convert-Table $tableHtml
        if ($table) {
            [void]$output.AddRange($table)
            [void]$output.Add("")
        }
        continue
    }

    # Figure (SVG) - just extract caption
    if ($line -match '<figure class="figure">') {
        while ($i -lt $lines.Count -and $lines[$i].Trim() -ne '</figure>') {
            $figLine = $lines[$i].Trim()
            if ($figLine -match '<figcaption>(.*?)</figcaption>') {
                [void]$output.Add("> *$($matches[1])*")
                [void]$output.Add("")
            }
            $i++
        }
        $i++
        continue
    }

    # Menu tree
    if ($line -match '<div class="menu-tree">') {
        $extract = ExtractDivContent $lines $i
        $menuHtml = $extract.Content
        $i = $extract.EndIndex
        $menuText = Convert-MenuTree $menuHtml
        [void]$output.Add('```')
        [void]$output.AddRange($menuText)
        [void]$output.Add('```')
        [void]$output.Add("")
        continue
    }

    # Phase card
    if ($line -match '<div class="phase-card">') {
        $extract = ExtractDivContent $lines $i
        $cardHtml = $extract.Content
        $i = $extract.EndIndex
        $title = [regex]::Match($cardHtml, '<h4>(.*?)</h4>').Groups[1].Value
        $duration = [regex]::Match($cardHtml, 'class="duration">(.*?)</div>').Groups[1].Value
        [void]$output.Add("**$title** ($duration)")
        $items = [regex]::Matches($cardHtml, '<li>(.*?)</li>')
        foreach ($item in $items) {
            $text = Convert-InlineHtml $item.Groups[1].Value
            [void]$output.Add("- $text")
        }
        [void]$output.Add("")
        continue
    }

    # Priority card
    if ($line -match '<div class="priority-card') {
        $extract = ExtractDivContent $lines $i
        $cardHtml = $extract.Content
        $i = $extract.EndIndex
        $title = [regex]::Match($cardHtml, 'class="ptitle">(.*?)</div>').Groups[1].Value
        $meta = [regex]::Match($cardHtml, 'class="pmeta">(.*?)</div>').Groups[1].Value
        [void]$output.Add("### $title")
        if ($meta) { [void]$output.Add("*$meta*"); [void]$output.Add("") }
        $items = [regex]::Matches($cardHtml, '<li>(.*?)</li>')
        foreach ($item in $items) {
            $text = Convert-InlineHtml $item.Groups[1].Value
            [void]$output.Add("- $text")
        }
        [void]$output.Add("")
        continue
    }

    # Task card
    if ($line -match '<div class="task-card') {
        $extract = ExtractDivContent $lines $i
        $cardHtml = $extract.Content
        $i = $extract.EndIndex
        $title = [regex]::Match($cardHtml, 'class="ttitle">(.*?)</div>').Groups[1].Value
        $meta = [regex]::Match($cardHtml, 'class="tmeta">(.*?)</div>').Groups[1].Value
        [void]$output.Add("#### $title")
        if ($meta) { [void]$output.Add("*$meta*"); [void]$output.Add("") }
        $items = [regex]::Matches($cardHtml, '<li>(.*?)</li>')
        foreach ($item in $items) {
            $text = Convert-InlineHtml $item.Groups[1].Value
            [void]$output.Add("- $text")
        }
        [void]$output.Add("")
        continue
    }

    # Scenario
    if ($line -match '<div class="scenario">') {
        $extract = ExtractDivContent $lines $i
        $scenHtml = $extract.Content
        $i = $extract.EndIndex
        $title = [regex]::Match($scenHtml, 'class="title">(.*?)</div>').Groups[1].Value
        if ($title) { [void]$output.Add("**$title**") }
        $scenHtml = [regex]::Replace($scenHtml, '<div class="title">.*?</div>', '')
        $items = [regex]::Matches($scenHtml, '<li>(.*?)</li>')
        if ($items.Count -gt 0) {
            foreach ($item in $items) {
                $text = Convert-InlineHtml $item.Groups[1].Value
                [void]$output.Add("- $text")
            }
        } else {
            $paras = [regex]::Matches($scenHtml, '<p>(.*?)</p>')
            foreach ($p in $paras) {
                $text = Convert-InlineHtml $p.Groups[1].Value
                [void]$output.Add($text)
            }
        }
        [void]$output.Add("")
        continue
    }

    # State grid
    # Each state-card nests state-icon/state-name/state-desc divs. Match each
    # field over the whole grid content. icon values may contain emoji
    # (surrogate pairs); use '[^<]*' there (icons never contain '<').
    if ($line -match '<div class="state-grid">') {
        $extract = ExtractDivContent $lines $i
        $gridHtml = $extract.Content
        $i = $extract.EndIndex
        $icons = [regex]::Matches($gridHtml, 'class="state-icon">([^<]*)</div>')
        $names = [regex]::Matches($gridHtml, 'class="state-name">(.*?)</div>')
        $descs = [regex]::Matches($gridHtml, 'class="state-desc">(.*?)</div>')
        $count = $names.Count
        for ($k = 0; $k -lt $count; $k++) {
            $icon = if ($k -lt $icons.Count) { $icons[$k].Groups[1].Value } else { '' }
            $name = $names[$k].Groups[1].Value
            $desc = if ($k -lt $descs.Count) { $descs[$k].Groups[1].Value } else { '' }
            [void]$output.Add("- $icon **$name**: $desc")
        }
        [void]$output.Add("")
        continue
    }

    # Blockquote
    if ($line -match '^<blockquote>') {
        $bqHtml = ''
        while ($i -lt $lines.Count -and $lines[$i].Trim() -ne '</blockquote>') {
            $bqHtml += $lines[$i].Trim() + " "
            $i++
        }
        $i++
        $text = Convert-InlineHtml $bqHtml.Trim()
        [void]$output.Add("> $text")
        [void]$output.Add("")
        continue
    }

    # Code block placeholder
    if ($line -match '^\[\[CODEBLOCK_(\d+)\]\]') {
        $idx = [int]$matches[1]
        $code = $codeBlocks[$idx]
        [void]$output.Add('```')
        $codeLines = $code -split "`n"
        foreach ($cl in $codeLines) {
            [void]$output.Add($cl)
        }
        [void]$output.Add('```')
        [void]$output.Add("")
        $i++
        continue
    }

    # Skip unrecognized lines
    $i++
}

# Step 5: Extract footer
$footerHtml = [regex]::Match($html, '(?s)<footer>(.*?)</footer>').Groups[1].Value
if ($footerHtml) {
    [void]$output.Add("---")
    [void]$output.Add("")
    # Extract rev-history first, then remove it from footer HTML
    $revContent = ''
    if ($footerHtml -match '(?s)<div class="rev-history">(.*?)</div>') {
        $revContent = $matches[1]
        $footerHtml = $footerHtml -replace '(?s)<div class="rev-history">.*?</div>', ''
    }
    # Extract non-rev-history paragraphs
    $footerParas = [regex]::Matches($footerHtml, '<p>(.*?)</p>')
    foreach ($p in $footerParas) {
        $text = Convert-InlineHtml $p.Groups[1].Value
        [void]$output.Add($text)
        [void]$output.Add("")
    }
    # Output rev-history
    if ($revContent) {
        $revHeading = [regex]::Match($revContent, '<p><strong>(.*?)</strong>').Groups[1].Value
        if (-not $revHeading) { $revHeading = 'Revision History' }
        [void]$output.Add("**$revHeading**")
        [void]$output.Add("")
        $revItems = [regex]::Matches($revContent, '<li>(.*?)</li>')
        foreach ($item in $revItems) {
            $text = Convert-InlineHtml $item.Groups[1].Value
            [void]$output.Add("- $text")
        }
        [void]$output.Add("")
    }
}

# Step 6: Write output
$finalText = $output -join "`n"
[System.IO.File]::WriteAllText($mdPath, $finalText + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "Conversion complete. Output lines: $($output.Count)"
