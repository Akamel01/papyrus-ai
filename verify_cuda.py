import torch

def diagnose_cuda():
    print("=" * 40)
    print("PyTorch CUDA Diagnostics")
    print("=" * 40)
    
    try:
        print(f"PyTorch Version: {torch.__version__}")
        print(f"CUDA Built-in: {torch.version.cuda}")
        print(f"CUDA Available: {torch.cuda.is_available()}")
        
        if hasattr(torch.backends, 'cudnn'):
            print(f"cuDNN Available: {torch.backends.cudnn.is_available()}")
        
        if not torch.cuda.is_available():
            print("\nAttempting raw CUDA initialization to catch errors...")
            try:
                torch._C._cuda_init()
                print("Raw init succeeded unexpectedly!")
            except Exception as e:
                print(f"Caught Exception during raw init:")
                print(f"Type: {type(e).__name__}")
                print(f"Message: {str(e)}")
                
    except Exception as e:
         print(f"Caught Exception during diagnostics: {str(e)}")
         
if __name__ == "__main__":
    diagnose_cuda()
