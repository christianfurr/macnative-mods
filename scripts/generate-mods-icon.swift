import AppKit

let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

func color(_ hex: UInt32, alpha: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 255) / 255,
            green: CGFloat((hex >> 8) & 255) / 255, blue: CGFloat(hex & 255) / 255, alpha: alpha)
}

func diamond(y: CGFloat, width: CGFloat, height: CGFloat) -> NSBezierPath {
    let shape = NSBezierPath()
    shape.move(to: NSPoint(x: 512, y: y + height / 2))
    shape.line(to: NSPoint(x: 512 + width / 2, y: y))
    shape.line(to: NSPoint(x: 512, y: y - height / 2))
    shape.line(to: NSPoint(x: 512 - width / 2, y: y))
    shape.close()
    shape.lineJoinStyle = .round
    return shape
}

func draw(_ size: Int) -> Data {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSGraphicsContext.saveGraphicsState()
    defer { NSGraphicsContext.restoreGraphicsState() }
    NSGraphicsContext.current = context
    context.cgContext.scaleBy(x: CGFloat(size) / 1024, y: CGFloat(size) / 1024)
    let plate = NSBezierPath(roundedRect: NSRect(x: 65, y: 65, width: 894, height: 894),
                             xRadius: 202, yRadius: 202)
    NSGradient(starting: color(0x263655), ending: color(0x101622))!.draw(in: plate, angle: -56)
    color(0x627497, alpha: 0.5).setStroke()
    plate.lineWidth = 8
    plate.stroke()

    for (height, top, bottom, outline) in [
        (CGFloat(364), UInt32(0x293863), UInt32(0x1A2442), UInt32(0x6377B5)),
        (CGFloat(484), UInt32(0x35549B), UInt32(0x253961), UInt32(0x789AF2)),
        (CGFloat(604), UInt32(0x92D9FF), UInt32(0x5892F7), UInt32(0xBCEAFF)),
    ] {
        let slab = diamond(y: height, width: 510, height: 252)
        NSGradient(starting: color(top), ending: color(bottom))!.draw(in: slab, angle: -70)
        color(outline).setStroke()
        slab.lineWidth = 18
        slab.stroke()
    }
    let mark = NSBezierPath()
    mark.move(to: NSPoint(x: 438, y: 604))
    mark.line(to: NSPoint(x: 586, y: 604))
    mark.move(to: NSPoint(x: 512, y: 555))
    mark.line(to: NSPoint(x: 512, y: 653))
    mark.lineCapStyle = .round
    mark.lineWidth = 24
    color(0x122955).setStroke()
    mark.stroke()
    return bitmap.representation(using: .png, properties: [:])!
}

let sizes = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
             (256, 1), (256, 2), (512, 1), (512, 2)]
for (points, scale) in sizes {
    let suffix = scale == 2 ? "@2x" : ""
    try draw(points * scale).write(to: directory.appendingPathComponent("icon_\(points)x\(points)\(suffix).png"))
}
