//
//  TextFileOutputStream.swift
//  MullvadVPN
//
//  Created by pronebird on 02/08/2020.
//  Copyright © 2020 Mullvad VPN AB. All rights reserved.
//

import Foundation

class TextFileOutputStream: TextOutputStream {
    private let writer: DispatchIO
    private let encoding: String.Encoding
    private let queue = DispatchQueue.global(qos: .utility)

    class func standardOutputStream(encoding: String.Encoding = .utf8) -> TextFileOutputStream {
        return TextFileOutputStream(
            fileDescriptor: FileHandle.standardOutput.fileDescriptor,
            encoding: encoding
        )
    }

    init(fileDescriptor: Int32, encoding: String.Encoding = .utf8) {
        self.encoding = encoding
        writer = DispatchIO(type: .stream, fileDescriptor: fileDescriptor, queue: queue) { errno in
            if errno != 0 {
                print("TextFileOutputStream: closed channel with error: \(errno)")
            }
        }
    }

    init?(
        fileURL: URL,
        createFile: Bool,
        filePermissions: mode_t = S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH,
        encoding: String.Encoding = .utf8
    ) {
        var oflag: Int32 = O_WRONLY
        var mode: mode_t = .zero
        if createFile {
            oflag |= O_CREAT
            mode = filePermissions
        }

        let queue = queue
        let writer = fileURL.path.withCString { filePathPointer -> DispatchIO? in
            return DispatchIO(
                type: .stream,
                path: filePathPointer,
                oflag: oflag,
                mode: mode,
                queue: queue,
                cleanupHandler: { errno in
                    if errno != 0 {
                        print("TextFileOutputStream: closed channel with error: \(errno)")
                    }
                }
            )
        }

        if let writer = writer {
            self.writer = writer
            self.encoding = encoding
        } else {
            return nil
        }
    }

    deinit {
        writer.close()
    }

    func write(_ string: String) {
        string.data(using: encoding)?.withUnsafeBytes { bytes in
            writer
                .write(
                    offset: .zero,
                    data: DispatchData(bytes: bytes),
                    queue: queue
                ) { done, data, errno in
                    if errno != 0 {
                        print("TextFileOutputStream: write error: \(errno)")
                    }
                }
        }
    }
}
