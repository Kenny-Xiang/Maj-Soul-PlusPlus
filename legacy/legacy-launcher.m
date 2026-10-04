#import <Foundation/Foundation.h>
#include <unistd.h>

int main(void) {
    @autoreleasepool {
        NSString *desktop = NSBundle.mainBundle.bundlePath.stringByDeletingLastPathComponent;
        NSString *script = [desktop stringByAppendingPathComponent:@"雀魂实时监听/launch.sh"];
        execl("/bin/zsh", "zsh", script.fileSystemRepresentation, NULL);
        return 1;
    }
}
