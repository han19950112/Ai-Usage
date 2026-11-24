import AppKit
import Foundation

let size = NSSize(width: 1024, height: 1024)
let image = NSImage(size: size)

image.lockFocus()

// 1. Draw rounded squircle
let rect = NSRect(x: 100, y: 100, width: 824, height: 824)
let path = NSBezierPath(roundedRect: rect, xRadius: 185, yRadius: 185)

// Shadow
let shadow = NSShadow()
shadow.shadowColor = NSColor.black.withAlphaComponent(0.4)
shadow.shadowOffset = NSSize(width: 0, height: -20)
shadow.shadowBlurRadius = 35
shadow.set()

// Gradient fill
let gradient = NSGradient(colors: [
    NSColor(red: 0.08, green: 0.12, blue: 0.22, alpha: 1.0),
    NSColor(red: 0.03, green: 0.05, blue: 0.10, alpha: 1.0)
])!
gradient.draw(in: path, angle: -45)

// Border stroke
NSGraphicsContext.saveGraphicsState()
shadow.shadowColor = nil
shadow.set()
let strokePath = NSBezierPath(roundedRect: rect.insetBy(dx: 3, dy: 3), xRadius: 182, yRadius: 182)
NSColor(red: 0.35, green: 0.65, blue: 1.0, alpha: 0.4).setStroke()
strokePath.lineWidth = 6
strokePath.stroke()
NSGraphicsContext.restoreGraphicsState()

// 2. Draw Center Icon Emoji 🛸
let emoji = "🛸" as NSString
let font = NSFont.systemFont(ofSize: 420)
let attrs: [NSAttributedString.Key: Any] = [.font: font]
let strSize = emoji.size(withAttributes: attrs)
let strRect = NSRect(
    x: (1024 - strSize.width) / 2,
    y: (1024 - strSize.height) / 2 + 10,
    width: strSize.width,
    height: strSize.height
)
emoji.draw(in: strRect, withAttributes: attrs)

image.unlockFocus()

// Save to iconset directory
let fm = FileManager.default
let iconsetPath = "/tmp/AgentCockpit.iconset"
try? fm.removeItem(atPath: iconsetPath)
try! fm.createDirectory(atPath: iconsetPath, withIntermediateDirectories: true)

let sizes: [(String, Int)] = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024)
]

for (name, px) in sizes {
    let resized = NSImage(size: NSSize(width: px, height: px))
    resized.lockFocus()
    image.draw(in: NSRect(x: 0, y: 0, width: px, height: px),
               from: NSRect(x: 0, y: 0, width: 1024, height: 1024),
               operation: .copy, fraction: 1.0)
    resized.unlockFocus()
    
    let tiff = resized.tiffRepresentation!
    let rep = NSBitmapImageRep(data: tiff)!
    let png = rep.representation(using: .png, properties: [:])!
    let outUrl = URL(fileURLWithPath: "\(iconsetPath)/\(name)")
    try! png.write(to: outUrl)
}

print("Iconset created successfully at \(iconsetPath)")
